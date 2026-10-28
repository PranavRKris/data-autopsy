# Sensor readings (second test plug-in)

One dataset of hourly temperature readings from five sensors, a ten-line manifest and one stale-feed
scenario. It exists to show the same tools and the same Incident Investigator mode work on a different project.

```bash
export SENSOR_DB_PATH=plugins/sensor_readings/sensors.duckdb
python plugins/sensor_readings/seed/seed_data.py --db "$SENSOR_DB_PATH" --scenario S0
autopsy validate plugins/sensor_readings/manifest.yaml
autopsy baseline plugins/sensor_readings/manifest.yaml
python plugins/sensor_readings/seed/seed_data.py --db "$SENSOR_DB_PATH" --scenario S1     # the feed goes stale
autopsy-platform/investigator/investigate.sh plugins/sensor_readings/manifest.yaml s1
autopsy grade autopsy-platform/reports/incident_sensor_readings_s1.md plugins/sensor_readings/expected_results.yaml S1
```

Automated in `autopsy-platform/tests/test_swaps.py::test_swap_the_project`.
