from datetime import datetime, timedelta, timezone
from pathlib import Path
import re
from typing import Any

import pandas as pd
from pydantic import BaseModel, Field


BASE_DIR = Path(__file__).resolve().parent
DATA_PATH = BASE_DIR / "trips.csv"
SCHEDULE_PATH = BASE_DIR / "schedule_v2.csv"
LOCAL_TIMEZONE = timezone(timedelta(hours=5, minutes=30))
ON_TIME_THRESHOLD_MINUTES = 4
PHONE_PATTERN = re.compile(r"(?<!\d)(?:\+\d{1,3}[-\s]?)?\d{10,15}(?!\d)")
PRIVATE_FIELD_TERMS = (
    "phone", "mobile", "contact", "complaint", "comment", "free_text", "message",
)

# Add abbreviated codes only after confirming their mapping to the 4xx class.
REC114_SERIES: set[str] = set()
TRIP_COLUMNS = (
    "trip_id",
    "route",
    "vehicle_series",
    "scheduled_departure",
    "scheduled_runtime_min",
    "actual_arrival",
    "tz_offset",
    "scheduled_lateness_min",
)
REQUIRED_COLUMNS = {
    *TRIP_COLUMNS,
}


class RouteSummary(BaseModel):
    route: str
    trip_count: int = Field(ge=0)
    average_delay_minutes: float
    median_delay_minutes: float
    p90_delay_minutes: float
    late_trip_count: int = Field(ge=0)
    on_time_percentage: float = Field(ge=0, le=100)


def redact_text(value: str) -> str:
    """Mask phone-number patterns in text that might be written to a log."""
    return PHONE_PATTERN.sub("[REDACTED_PHONE]", value)


def sanitize_for_output(value: Any) -> Any:
    """Remove private fields and mask phone numbers from a tool response."""
    if isinstance(value, dict):
        return {
            key: "[REDACTED]" if any(term in str(key).lower() for term in PRIVATE_FIELD_TERMS)
            else sanitize_for_output(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [sanitize_for_output(item) for item in value]
    if isinstance(value, tuple):
        return tuple(sanitize_for_output(item) for item in value)
    if isinstance(value, str):
        return redact_text(value)
    return value


def _read_csv(path: Path, required: set[str]) -> pd.DataFrame:
    df = pd.read_csv(path, dtype="string", keep_default_na=False)
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"{Path(path).name}: missing required columns: {sorted(missing)}")
    # Only the documented fields enter processing or tool responses.
    return df[sorted(required)].apply(lambda column: column.str.strip())


def _parse_timestamp(values: pd.Series) -> pd.Series:
    """Accept ISO, day-first, and Excel serial date/times."""
    parsed = pd.Series(pd.NaT, index=values.index, dtype="datetime64[ns]")
    for date_format in ("%Y-%m-%d %H:%M", "%d-%m-%Y %H:%M"):
        parsed = parsed.fillna(pd.to_datetime(values, format=date_format, errors="coerce"))
    serial_values = pd.to_numeric(values.where(parsed.isna()), errors="coerce")
    excel_dates = pd.to_datetime(serial_values, unit="D", origin="1899-12-30", errors="coerce")
    return parsed.fillna(excel_dates)


def adjust_arrival_to_local_time(
    arrival: pd.Series,
    tz_offset: pd.Series,
) -> tuple[pd.Series, pd.Series]:
    """Convert device-reported arrival timestamps to Asia/Kolkata (+05:30)."""
    offset = tz_offset.str.extract(r"^([+-]?)(\d{1,2}):(\d{2})$")
    hours = pd.to_numeric(offset[1], errors="coerce")
    minutes = pd.to_numeric(offset[2], errors="coerce")
    valid_offset = hours.between(0, 14) & minutes.between(0, 59) & (hours.ne(14) | minutes.eq(0))
    signs = offset[0].map({"+": 1, "-": -1}).fillna(1)
    offset_minutes = ((hours * 60 + minutes) * signs).where(valid_offset)
    offset_delta = pd.to_timedelta(offset_minutes.fillna(0).astype(float), unit="m")
    utc_arrival = (arrival - offset_delta).where(valid_offset.fillna(False))
    local_arrival = utc_arrival.dt.tz_localize("UTC").dt.tz_convert(LOCAL_TIMEZONE)
    return local_arrival, valid_offset


def _flag(df: pd.DataFrame, mask: pd.Series, reason: str) -> None:
    mask = mask.fillna(False)
    current = df.loc[mask, "exclusion_reason"]
    separator = current.ne("").map({True: ";", False: ""})
    df.loc[mask, "exclusion_reason"] = current + separator + reason


def _apply_revised_schedule(df: pd.DataFrame) -> None:
    series = df["vehicle_series"].str.lower()
    eligible = series.str.fullmatch(r"4\d{2}|4xx") | series.isin(REC114_SERIES)
    df["rec114_mapping_unresolved"] = False

    if not SCHEDULE_PATH.exists():
        _flag(df, eligible, "missing_revised_schedule")
        df.attrs["schedule_warning"] = "schedule_v2.csv is missing; REC-114 coverage could not be checked."
        return

    schedule = _read_csv(SCHEDULE_PATH, {"route", "revised_runtime_min", "effective_date"})
    schedule["effective_date"] = pd.to_datetime(schedule["effective_date"], format="%Y-%m-%d", errors="coerce")
    schedule["revised_runtime_min"] = pd.to_numeric(schedule["revised_runtime_min"], errors="coerce")
    valid_runtime = schedule["revised_runtime_min"].gt(0) & schedule["revised_runtime_min"].lt(float("inf"))
    if (schedule["route"].eq("") | schedule["effective_date"].isna() | ~valid_runtime.fillna(False)).any():
        raise ValueError("schedule_v2.csv contains an invalid route, effective date, or runtime")
    if schedule.duplicated(["route", "effective_date"]).any():
        raise ValueError("schedule_v2.csv has duplicate route/effective_date entries")

    _flag(df, eligible & ~df["route"].isin(schedule["route"]), "missing_revised_schedule")
    for revision in schedule.sort_values("effective_date").itertuples(index=False):
        effective = revision.effective_date.tz_localize(LOCAL_TIMEZONE)
        applies = df["route"].eq(revision.route) & df["scheduled_departure_local"].ge(effective)
        df.loc[applies & eligible, "runtime_min"] = float(revision.revised_runtime_min)
        # Two-digit suffixes alone cannot establish the original vehicle class.
        unresolved = applies & ~eligible & series.str.fullmatch(r"\d{1,2}")
        df.loc[unresolved, "rec114_mapping_unresolved"] = True


def load_trips() -> pd.DataFrame:
    """Process every trip, preserving source values and exclusion reasons."""

    df = _read_csv(DATA_PATH, REQUIRED_COLUMNS)
    df["exclusion_reason"] = ""
    _flag(df, df["trip_id"].eq(""), "missing_trip_id")
    _flag(df, df["route"].eq(""), "missing_route")
    _flag(df, df["vehicle_series"].eq(""), "missing_vehicle_series")
    _flag(df, df["trip_id"].ne("") & df["trip_id"].duplicated(keep=False), "duplicate_trip_id")

    departure = _parse_timestamp(df["scheduled_departure"])
    arrival = _parse_timestamp(df["actual_arrival"])
    df["scheduled_departure_local"] = departure.dt.tz_localize(LOCAL_TIMEZONE)
    df["trip_date"] = departure.dt.strftime("%Y-%m-%d")
    _flag(df, departure.isna(), "invalid_departure")
    _flag(df, arrival.isna(), "invalid_arrival")

    # The offset belongs to the device's arrival, not the local departure.
    df["actual_arrival_local"], valid_offset = adjust_arrival_to_local_time(
        arrival, df["tz_offset"]
    )
    df["actual_arrival_timezone"] = "+05:30"
    _flag(df, ~valid_offset.fillna(False), "invalid_tz_offset")

    df["runtime_min"] = pd.to_numeric(df["scheduled_runtime_min"], errors="coerce").astype(float)
    _apply_revised_schedule(df)
    runtime_valid = df["runtime_min"].gt(0) & df["runtime_min"].lt(float("inf"))
    runtime = pd.to_timedelta(
        df["runtime_min"].where(runtime_valid, 0), unit="m", errors="coerce"
    ).where(runtime_valid)
    _flag(df, ~runtime_valid | runtime.isna(), "invalid_runtime")
    df["scheduled_arrival"] = df["scheduled_departure_local"] + runtime
    df["actual_runtime"] = (df["actual_arrival_local"] - df["scheduled_departure_local"]).dt.total_seconds() / 60
    _flag(df, df["actual_runtime"].lt(0), "arrival_before_departure")

    df["is_usable"] = df["exclusion_reason"].eq("")
    df["scheduled_lateness_min"] = (
        df["actual_arrival_local"] - df["scheduled_arrival"]
    ).dt.total_seconds() / 60
    df.loc[~df["is_usable"], "scheduled_lateness_min"] = pd.NA
    df["on_time"] = df["is_usable"] & df["scheduled_lateness_min"].le(ON_TIME_THRESHOLD_MINUTES)
    # Calculations use timezone-aware local timestamps; return clean local wall-clock values.
    for column in ("scheduled_departure_local", "scheduled_arrival", "actual_arrival_local"):
        df[column] = df[column].dt.tz_localize(None)
    derived_columns = [column for column in df.columns if column not in TRIP_COLUMNS]
    
    trips = df[[*TRIP_COLUMNS, *derived_columns]]
    try:
        trips.to_csv(BASE_DIR / "trips_processed.csv", index=False)
    except PermissionError:
        trips.attrs["debug_export_warning"] = "trips_processed.csv is open elsewhere, so the debug export was not updated."

    return trips


def _data_quality(df: pd.DataFrame) -> dict:
    rejected = df.loc[~df["is_usable"]]
    reason_counts = rejected["exclusion_reason"].str.get_dummies(sep=";").sum()
    warnings = [
        "Device UTC offsets are trusted as supplied; no clock corrections are inferred.",
        "Unparseable timestamps (including numeric spreadsheet dates) and arrivals before scheduled departure are excluded; positive outliers are retained.",
    ]
    unresolved_count = int(df["rec114_mapping_unresolved"].sum())
    if unresolved_count:
        warnings.append(
            "REC-114 mapping is unresolved for abbreviated vehicle codes on revised routes. "
            "Their export timetable is used provisionally. Set REC114_SERIES only after confirming the mapping."
        )
    if "schedule_warning" in df.attrs:
        warnings.append(df.attrs["schedule_warning"])
    if "debug_export_warning" in df.attrs:
        warnings.append(df.attrs["debug_export_warning"])
    return {
        "input_rows": len(df),
        "usable_rows": int(df["is_usable"].sum()),
        "excluded_rows": len(rejected),
        "exclusion_counts": {reason: int(count) for reason, count in reason_counts.items()},
        "excluded_trips": rejected[["trip_id", "route", "exclusion_reason"]].to_dict(orient="records"),
        "non_local_offset_rows": int(df["tz_offset"].ne("+05:30").sum()),
        "rec114_unresolved_rows": unresolved_count,
        "warnings": warnings,
    }


def get_route_report(date: str | None = None, limit: int = 5) -> dict:
    """Summarize one local departure date, or the full CSV when date is omitted."""
    
    if date is not None:
        try:
            parsed_date = datetime.strptime(date, "%Y-%m-%d")
        except (TypeError, ValueError):
            raise ValueError("date must use YYYY-MM-DD format") from None
        if parsed_date.strftime("%Y-%m-%d") != date:
            raise ValueError("date must use YYYY-MM-DD format")
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100:
        raise ValueError("limit must be an integer between 1 and 100")

    trips = load_trips()
    
        
    dates = sorted(trips["trip_date"].dropna().unique().tolist())
    selected = trips if date is None else trips.loc[trips["trip_date"].eq(date)].copy()
    usable = selected.loc[selected["is_usable"]]
    quality = _data_quality(selected)
    quality["file_rows_with_unknown_date"] = int(trips["trip_date"].isna().sum())

    summary = usable.groupby("route").agg(
        trip_count=("scheduled_lateness_min", "size"),
        average_delay_minutes=("scheduled_lateness_min", "mean"),
        median_delay_minutes=("scheduled_lateness_min", "median"),
        p90_delay_minutes=("scheduled_lateness_min", lambda values: values.quantile(0.9)),
        late_trip_count=("on_time", lambda values: int((~values).sum())),
        on_time_percentage=("on_time", "mean"),
                ).reset_index()
    
    summary["on_time_percentage"] *= 100
    summary = summary.sort_values(["average_delay_minutes", "route"], ascending=[False, True])
    metrics = ["average_delay_minutes", "median_delay_minutes", "p90_delay_minutes", "on_time_percentage"]
    summary[metrics] = summary[metrics].round(2)
    summary.to_csv(BASE_DIR / "summary_data.csv", index=False)

    rows = [RouteSummary(**row).model_dump() for row in summary.head(limit).to_dict(orient="records")]
    
    
    return {
        "date": date,
        "available_dates": dates,
        "routes": rows,
        "route_count": len(rows),
        "total_usable_routes": len(summary),
        "routes_without_usable_trips": sorted(set(selected["route"]) - set(usable["route"]) - {""}),
        "methodology": {
            "timezone": "Asia/Kolkata (+05:30)",
            "date_basis": "local scheduled departure",
            "delay": "actual local arrival minus (local scheduled departure plus applicable runtime)",
            "negative_delay": "early arrival; retained in the signed mean",
            "on_time_threshold_minutes": ON_TIME_THRESHOLD_MINUTES,
            "ranking": "descending signed mean delay; route code breaks ties; this is a descriptive ranking, not a final operational verdict",
                        },
        "data_quality": quality,
            }



