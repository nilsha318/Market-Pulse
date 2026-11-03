-- Run this in pgAdmin's Query Tool while connected to the default `postgres` database.
-- PostgreSQL does not support CREATE DATABASE inside a transaction.
-- If market_pulse already exists, skip this statement.
CREATE DATABASE market_pulse
    WITH ENCODING 'UTF8'
    TEMPLATE template0;
