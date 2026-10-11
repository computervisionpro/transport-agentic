# Operations Decision

## Routes Requiring Attention

The three routes with the worst average delays were **R-14, R-35, and R-33**.

- **R-14:** average delay **8.07 minutes**; median delay **8.0 minutes**; on-time **20.34%**; **118 usable trips**.
- **R-35:** average delay **8.05 minutes**; median delay **2.0 minutes**; on-time **73.48%**; **132 usable trips**.
- **R-33:** average delay **5.36 minutes**; median delay **5.0 minutes**; on-time **38.46%**; **104 usable trips**.

## Data Basis And Limitations

- **Excluded records:** 39 of 5,292 input rows, all because arrival occurred before departure. The ranking uses **5,253 usable rows**.
- **On-time definition:** 4 minutes or less, based on the provided data.
- **Timetable limitation:** REC-114 mapping remains unresolved for **190 rows**, so the export timetable was used provisionally; this could affect the route comparisons.
- Delays are ranked by signed average delay, with early arrivals retained in the calculation.
- **R-35** needs targeted investigation: its 8.05-minute mean delay sits alongside a 2-minute median and a 49.8-minute P90 delay. This indicates a smaller set of severely late trips is pulling up its average

## On-Time Threshold Rationale

The 4-minute on-time threshold includes a 1-minute operating buffer above the 3-minute average-delay baseline that most routes meet.

- Of 40 routes, **33** have an average delay of 3 minutes or less.
- **7** routes have an average delay above 3 minutes; **5** are above 4 minutes; and **3** are above 5 minutes.
- **1,335 trips** exceeded the selected 4-minute threshold. This is the sum of `late_trip_count` in `summary_data.csv`.
.
