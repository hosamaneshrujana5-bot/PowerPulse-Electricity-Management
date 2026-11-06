
CREATE DATABASE IF NOT EXISTS electricity_analysis;

USE electricity_analysis;

CREATE TABLE IF NOT EXISTS consumers (
    consumer_id INT PRIMARY KEY AUTO_INCREMENT,
    consumer_type VARCHAR(30) NOT NULL,
    region VARCHAR(50) NOT NULL
);

CREATE TABLE IF NOT EXISTS meters (
    meter_id INT PRIMARY KEY AUTO_INCREMENT,
    consumer_id INT NOT NULL,
    meter_code VARCHAR(30) UNIQUE NOT NULL,
    FOREIGN KEY (consumer_id)
        REFERENCES consumers(consumer_id)
);

CREATE TABLE IF NOT EXISTS meter_readings (
    reading_id INT PRIMARY KEY AUTO_INCREMENT,
    meter_id INT NOT NULL,
    reading_date DATE NOT NULL,
    cumulative_kwh DECIMAL(12,2) NOT NULL,
    FOREIGN KEY (meter_id)
        REFERENCES meters(meter_id),
    UNIQUE (meter_id, reading_date),
    CHECK (cumulative_kwh >= 0)
);

USE electricity_analysis;
SHOW TABLES;
USE electricity_analysis;

SELECT * FROM consumers;

SELECT * FROM meters;

SELECT * FROM meter_readings;