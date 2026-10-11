#----------------------------------------------------------------------------------------------
#MODBUS TCP Server
#----------------------------------------------------------------------------------------------
FROM python:3.10-slim

WORKDIR /app

# Install system dependencies (only if required) and clean up apt cache
RUN apt-get update && apt-get install -y --no-install-recommends \
    nano \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir pymodbus==3.6.9

COPY modbus_server.py /app/modbus_server.py
COPY modbus_server_config.ini /app/modbus_server_config.ini
COPY modbus_tags.csv /app/modbus_tags.csv

EXPOSE 502

ENTRYPOINT ["python", "/app/modbus_server.py"]
CMD ["--config", "/app/modbus_server_config.ini"]
