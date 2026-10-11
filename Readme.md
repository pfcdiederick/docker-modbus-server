----------------------------------------------------------------------------------------------
modbus-server
----------------------------------------------------------------------------------------------
Modbus TCP server (slave) that serves the registers defined in modbus_tags.csv.
Any Modbus TCP client can read and write these registers. Writes to a tag are logged
with their engineering value.

FILES:
modbus_server.py          the server
modbus_server_config.ini  parameter file: listen address / port, default unit id, word / byte order
modbus_tags.csv           tag list: which registers the server serves and their initial values

TAG FILE COLUMNS (modbus_tags.csv):
name           tag name, used in the log
unit_id        Modbus unit / slave id (empty = unit_id from the config file)
function_code  Modbus function code a client uses for this tag; determines the data table:
                 1, 5, 15  = coils              (data_type bool)
                 2         = discrete inputs    (data_type bool)
                 3, 6, 16  = holding registers  (FC6: data_type int16 or uint16)
                 4         = input registers
address        register address (0-based)
data_type      int16 | uint16 | int32 | uint32 | float32 | int64 | uint64 | float64 | bool
scale          value = raw * scale + offset (empty = 1)
offset         (empty = 0). The initial value is converted with raw = (value - offset) / scale
unit           engineering unit, shown in the log (optional)
value          initial value at startup (empty = 0, bool: 1/true/on/yes)
Rows with a name starting with # are skipped.

Each unit id in the tag file gets its own set of tables, each covering addresses 0..65535,
so a client can also access addresses that are not in the tag file (value 0).
Requests for a unit id that is not in the tag file are not answered.

CURRENT TAGS:
ActualValue    unit 1, holding registers 0-1, float32
Setpoint       unit 1, holding register 10,   int16

BUILD:
docker build -t modbus-server .

OPTIONAL: docker build --platform=linux/arm/v7 -t modbus-server .

RUN:
The parameter file and tag file are baked into the image by the Dockerfile:

docker run -d \
  --name modbus-server \
  --restart unless-stopped \
  -p 502:502 \
  modbus-server:latest

To change the parameters without rebuilding, mount your own files over the ones in the image:

docker run -d \
  --name modbus-server \
  --restart unless-stopped \
  -p 502:502 \
  -v $(pwd)/modbus_server_config.ini:/app/modbus_server_config.ini \
  -v $(pwd)/modbus_tags.csv:/app/modbus_tags.csv \
  modbus-server:latest

LOGS:
docker logs -f modbus-server

SAVE:
docker save -o modbus-server.tar modbus-server:latest

LOAD:
docker load -i modbus-server.tar
