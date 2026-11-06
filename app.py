from flask import Flask, render_template, request, redirect, url_for, flash, make_response
from database import get_connection
from datetime import date, datetime
import csv
import io
import json

app = Flask(__name__)
app.secret_key = "electricity-dashboard-demo-key"

ALERT_THRESHOLD_KWH = 500.0


def get_dashboard_data():
    """Load shared dashboard data from the existing MySQL database."""
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)

    try:
        cursor.execute("SELECT COUNT(*) AS total FROM consumers")
        total_consumers = cursor.fetchone()["total"]

        cursor.execute("SELECT COUNT(*) AS total FROM meters")
        total_meters = cursor.fetchone()["total"]

        cursor.execute("SELECT COUNT(*) AS total FROM meter_readings")
        total_readings = cursor.fetchone()["total"]

        cursor.execute("""
            SELECT COALESCE(SUM(consumption), 0) AS total
            FROM (
                SELECT cumulative_kwh -
                       LAG(cumulative_kwh) OVER (
                           PARTITION BY meter_id
                           ORDER BY reading_date, reading_id
                       ) AS consumption
                FROM meter_readings
            ) AS usage_data
        """)
        total_consumption = float(cursor.fetchone()["total"] or 0)

        cursor.execute("""
            SELECT reading_date, meter_id, SUM(consumption) AS daily_usage
            FROM (
                SELECT reading_date,
                       meter_id,
                       cumulative_kwh -
                       LAG(cumulative_kwh) OVER (
                           PARTITION BY meter_id
                           ORDER BY reading_date, reading_id
                       ) AS consumption
                FROM meter_readings
            ) AS usage_data
            WHERE consumption IS NOT NULL
            GROUP BY reading_date, meter_id
            ORDER BY reading_date, meter_id
        """)
        usage_rows = cursor.fetchall()

        cursor.execute("""
            SELECT c.consumer_id, c.consumer_type, c.region,
                   m.meter_id, m.meter_code
            FROM consumers c
            LEFT JOIN meters m ON c.consumer_id = m.consumer_id
            ORDER BY c.consumer_id, m.meter_id
        """)
        consumers = cursor.fetchall()

        cursor.execute("""
            SELECT meter_id, meter_code
            FROM meters
            ORDER BY meter_id
        """)
        meters_list = cursor.fetchall()

        cursor.execute("""
            SELECT r.reading_id, r.meter_id, m.meter_code,
                   r.reading_date, r.cumulative_kwh
            FROM meter_readings r
            JOIN meters m ON r.meter_id = m.meter_id
            ORDER BY r.reading_date DESC, r.reading_id DESC
            LIMIT 100
        """)
        readings = cursor.fetchall()

        cursor.execute("""
            SELECT c.consumer_id, c.consumer_type, c.region,
                   m.meter_id, m.meter_code,
                   MAX(r.cumulative_kwh) - MIN(r.cumulative_kwh) AS meter_range,
                   COUNT(r.reading_id) AS reading_count
            FROM consumers c
            JOIN meters m ON c.consumer_id = m.consumer_id
            JOIN meter_readings r ON m.meter_id = r.meter_id
            GROUP BY c.consumer_id, c.consumer_type, c.region,
                     m.meter_id, m.meter_code
            HAVING COUNT(r.reading_id) > 1
            ORDER BY meter_range DESC
        """)
        meter_usage = cursor.fetchall()

        alerts = [
            row for row in meter_usage
            if float(row["meter_range"] or 0) > ALERT_THRESHOLD_KWH
        ]

        # Aggregate consumption by meter using the differences between readings.
        cursor.execute("""
            SELECT meter_id, SUM(consumption) AS total_usage
            FROM (
                SELECT meter_id,
                       cumulative_kwh -
                       LAG(cumulative_kwh) OVER (
                           PARTITION BY meter_id
                           ORDER BY reading_date, reading_id
                       ) AS consumption
                FROM meter_readings
            ) AS usage_data
            WHERE consumption IS NOT NULL
            GROUP BY meter_id
            ORDER BY total_usage DESC
        """)
        meter_consumption = cursor.fetchall()

        cursor.execute("""
            SELECT m.meter_code, r.reading_date, r.cumulative_kwh
            FROM meter_readings r
            JOIN meters m ON r.meter_id = m.meter_id
            ORDER BY r.reading_date DESC, r.reading_id DESC
            LIMIT 5
        """)
        recent_readings = cursor.fetchall()

        return {
            "total_consumers": total_consumers,
            "total_meters": total_meters,
            "total_readings": total_readings,
            "total_consumption": total_consumption,
            "usage_rows": usage_rows,
            "consumers": consumers,
            "meters_list": meters_list,
            "readings": readings,
            "alerts": alerts,
            "meter_consumption": meter_consumption,
            "recent_readings": recent_readings,
            "today": date.today().isoformat(),
            "alert_threshold": ALERT_THRESHOLD_KWH,
            "chart_labels": json.dumps([
                f"{row['reading_date']} (Meter {row['meter_id']})"
                for row in usage_rows
            ]),
            "chart_values": json.dumps([
                float(row["daily_usage"] or 0) for row in usage_rows
            ]),
            "meter_labels": json.dumps([
                str(row["meter_id"]) for row in meter_consumption
            ]),
            "meter_values": json.dumps([
                float(row["total_usage"] or 0) for row in meter_consumption
            ]),
        }
    finally:
        cursor.close()
        conn.close()


@app.context_processor
def inject_navigation_counts():
    # Keep the sidebar alert badge useful on every page.
    try:
        data = get_dashboard_data()
        return {"sidebar_alert_count": len(data["alerts"])}
    except Exception:
        return {"sidebar_alert_count": 0}


@app.route("/")
def dashboard():
    try:
        data = get_dashboard_data()
        return render_template("dashboard.html", page="dashboard", **data)
    except Exception as exc:
        app.logger.exception("Could not load dashboard")
        return render_template(
            "error.html", page="dashboard",
            error_message="The dashboard could not load data from MySQL. "
                          "Check database.py and the database connection."
        ), 500


@app.route("/consumption")
def consumption():
    try:
        data = get_dashboard_data()
        return render_template("consumption.html", page="consumption", **data)
    except Exception:
        app.logger.exception("Could not load consumption page")
        return render_template("error.html", page="consumption",
                               error_message="Could not load consumption data. Check the terminal for details."), 500


@app.route("/consumers")
def consumers_page():
    try:
        data = get_dashboard_data()
        return render_template("consumers.html", page="consumers", **data)
    except Exception:
        app.logger.exception("Could not load consumers page")
        return render_template("error.html", page="consumers",
                               error_message="Could not load consumer and meter details. Check the terminal for details."), 500


@app.route("/readings")
def readings_page():
    try:
        data = get_dashboard_data()
        return render_template("readings.html", page="readings", **data)
    except Exception:
        app.logger.exception("Could not load readings page")
        return render_template("error.html", page="readings",
                               error_message="Could not load meter readings. Check the terminal for details."), 500


@app.route("/add-reading", methods=["POST"])
def add_reading():
    meter_id = request.form.get("meter_id", "").strip()
    reading_date = request.form.get("reading_date", "").strip()
    cumulative_kwh = request.form.get("cumulative_kwh", "").strip()
    conn = None
    cursor = None

    try:
        meter_id = int(meter_id)
        cumulative_kwh = float(cumulative_kwh)
        datetime.strptime(reading_date, "%Y-%m-%d")

        if cumulative_kwh < 0:
            raise ValueError("Cumulative reading must not be negative.")

        conn = get_connection()
        cursor = conn.cursor(dictionary=True)

        cursor.execute("SELECT meter_id FROM meters WHERE meter_id = %s", (meter_id,))
        if cursor.fetchone() is None:
            flash("The selected meter does not exist.", "error")
            return redirect(url_for("readings_page"))

        cursor.execute("""
            SELECT reading_date, cumulative_kwh
            FROM meter_readings
            WHERE meter_id = %s
            ORDER BY reading_date DESC, reading_id DESC
            LIMIT 1
        """, (meter_id,))
        previous = cursor.fetchone()

        if previous:
            if reading_date < str(previous["reading_date"]):
                flash("The reading date cannot be earlier than the latest saved date for this meter.", "error")
                return redirect(url_for("readings_page"))
            if cumulative_kwh < float(previous["cumulative_kwh"]):
                flash("The cumulative reading cannot be lower than the latest saved reading.", "error")
                return redirect(url_for("readings_page"))
            if reading_date == str(previous["reading_date"]):
                flash("A reading already exists for this meter on that date. Choose a different date.", "error")
                return redirect(url_for("readings_page"))

        cursor.execute("""
            INSERT INTO meter_readings (meter_id, reading_date, cumulative_kwh)
            VALUES (%s, %s, %s)
        """, (meter_id, reading_date, cumulative_kwh))
        conn.commit()
        flash("Meter reading saved successfully.", "success")

    except (ValueError, TypeError):
        flash("Enter a valid meter, date, and non-negative cumulative reading.", "error")
    except Exception:
        if conn:
            conn.rollback()
        app.logger.exception("Failed to save meter reading")
        flash("Could not save the reading. Check the VS Code terminal for details.", "error")
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()

    return redirect(url_for("readings_page"))


@app.route("/alerts")
def alerts_page():
    try:
        data = get_dashboard_data()
        return render_template("alerts.html", page="alerts", **data)
    except Exception:
        app.logger.exception("Could not load alerts")
        return render_template("error.html", page="alerts",
                               error_message="Could not load alert data. Check the terminal for details."), 500


@app.route("/reports")
def reports_page():
    try:
        data = get_dashboard_data()
        return render_template("reports.html", page="reports", **data)
    except Exception:
        app.logger.exception("Could not load reports")
        return render_template("error.html", page="reports",
                               error_message="Could not load report data. Check the terminal for details."), 500


@app.route("/reports/export.csv")
def export_csv():
    try:
        data = get_dashboard_data()
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["Reading ID", "Meter ID", "Meter Code", "Reading Date", "Cumulative Reading (kWh)"])
        for row in data["readings"]:
            writer.writerow([
                row["reading_id"], row["meter_id"], row["meter_code"],
                row["reading_date"], row["cumulative_kwh"]
            ])
        response = make_response(output.getvalue())
        response.headers["Content-Disposition"] = "attachment; filename=electricity_readings.csv"
        response.headers["Content-Type"] = "text/csv; charset=utf-8"
        return response
    except Exception:
        app.logger.exception("CSV export failed")
        flash("Could not export the report. Check the terminal for details.", "error")
        return redirect(url_for("reports_page"))


@app.route("/settings", methods=["GET", "POST"])
def settings_page():
    global ALERT_THRESHOLD_KWH
    if request.method == "POST":
        try:
            threshold = float(request.form.get("alert_threshold", "500"))
            if threshold <= 0:
                raise ValueError
            ALERT_THRESHOLD_KWH = threshold
            flash(f"Demo alert threshold updated to {threshold:g} kWh for this running session.", "success")
        except (ValueError, TypeError):
            flash("Enter a threshold greater than zero.", "error")
        return redirect(url_for("settings_page"))
    return render_template("settings.html", page="settings", alert_threshold=ALERT_THRESHOLD_KWH)


@app.route("/about")
def about_page():
    return render_template("about.html", page="about")


if __name__ == "__main__":
    app.run(debug=True)
