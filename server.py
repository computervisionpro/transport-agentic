from mcp.server import MCPServer
from ops_logic import get_route_report, sanitize_for_output, load_trips

mcp = MCPServer("Cityflo Operations")


# decorator registers func as a tool
@mcp.tool()
def route_performance(date: str | None = None, limit: int = 5) -> dict:
    """Return route metrics and CSV processing diagnostics.

    Args:
        date: Local departure date in YYYY-MM-DD format; omit for the entire CSV.
        limit: Maximum number of routes to return, between 1 and 100.
    """
    return sanitize_for_output(get_route_report(date, limit))

@mcp.tool()
def trip_level_information(trip_id: str | None = None, route: str | None = None,
                            date: str | None = None, limit: int = 20,
                                    ) -> dict:
    """Return a limited set of processed trip-level records."""
    
    trips = load_trips()
    # print()
    trips = trips[['trip_id', 'route', 'vehicle_series', 'scheduled_departure', 'scheduled_runtime_min', 'scheduled_lateness_min', 'exclusion_reason', 'trip_date', 'actual_arrival_local', 'actual_arrival_timezone', 'runtime_min', 'rec114_mapping_unresolved', 'scheduled_arrival', 'actual_runtime', 'is_usable', 'on_time']]

    if trip_id:
        trips = trips.loc[trips["trip_id"].eq(trip_id)]
    if route:
        trips = trips.loc[trips["route"].eq(route)]
    if date:
        trips = trips.loc[trips["trip_date"].eq(date)]

    records = trips.head(limit).copy()
    for column in records.select_dtypes(include=["datetime64[ns]", "datetimetz"]).columns:
        records[column] = records[column].astype(str)

    return sanitize_for_output({
        "record_count": len(records),
        "records": records.to_dict(orient="records"),
    })


if __name__ == "__main__":
    mcp.run(transport="stdio")
