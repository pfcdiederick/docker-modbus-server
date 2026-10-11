# Modbus TCP Server – Installation from `modbus-server.tar`

This package contains a ready-built Docker image of the Modbus TCP server:

| File                       | Purpose                                            |
|----------------------------|----------------------------------------------------|
| `modbus-server.tar`        | Docker image `modbus-server:latest` (linux/amd64)  |
| `modbus_server_config.ini` | Optional: own parameter file (address, port, ...)  |
| `modbus_tags.csv`          | Optional: own tag list                             |

> **Architecture:** this image is built for **linux/amd64** (normal PC / server).
> It will **not** run on an ARM device such as a WAGO PFC200 (armv7).
> See [section 0](#0-check-the-cpu-architecture-first) before you install.

---

## 0. Check the CPU architecture first

A Docker image only runs on the CPU architecture it was built for. Check the
architecture of the target machine:

```bash
uname -m
```

| Output of `uname -m`  | Architecture   | Can use this `modbus-server.tar`?          |
|-----------------------|----------------|--------------------------------------------|
| `x86_64`              | linux/amd64    | Yes – continue with step 1                 |
| `armv7l`              | linux/arm/v7   | No – build an ARM image first (see below)  |
| `aarch64`             | linux/arm64    | No – build an ARM image first (see below)  |

Typical devices:

| Device                                         | Architecture  |
|------------------------------------------------|---------------|
| Normal PC, server, virtual machine             | linux/amd64   |
| WAGO PFC200 / PFC100 / Touch Panel 600 / Edge Controller | linux/arm/v7 |
| WAGO PFC300, Raspberry Pi 4/5 (64-bit OS)      | linux/arm64   |

> Always check with `uname -m` on the device itself; the table is only a guide.

To check the architecture of an image (on the build PC, or after `docker load`):

```bash
docker inspect -f '{{.Os}}/{{.Architecture}}{{if .Variant}}/{{.Variant}}{{end}}' modbus-server:latest
```

### Building the image for ARM

Do this on the build PC (amd64) in the project folder (the folder with the `Dockerfile`).

1. One-time setup: install the QEMU emulators, so an amd64 PC can build ARM images.

   ```bash
   docker run --privileged --rm tonistiigi/binfmt --install arm,arm64
   ```

2. Build the image for the target platform:

   ```bash
   # WAGO PFC200 / PFC100 / TP600 / Edge Controller (32-bit ARM)
   docker build --platform=linux/arm/v7 -t modbus-server:latest .

   # PFC300, Raspberry Pi 64-bit (64-bit ARM)
   docker build --platform=linux/arm64 -t modbus-server:latest .
   ```

3. Check the result. It should print `linux/arm/v7` (or `linux/arm64`):

   ```bash
   docker inspect -f '{{.Os}}/{{.Architecture}}{{if .Variant}}/{{.Variant}}{{end}}' modbus-server:latest
   ```

4. Save it to a tar file. Use a name that shows the architecture, so the files are not mixed up:

   ```bash
   docker save modbus-server:latest > modbus-server-armv7.tar
   ```

5. Continue with step 1, using `modbus-server-armv7.tar` instead of `modbus-server.tar`.

> **Note:** the build PC cannot run the ARM image at full speed to test it (emulation
> is slow), so test it on the device itself (step 4).
>
> **Note for WAGO controllers:** Docker must first be installed and enabled on the
> controller (via the WAGO Docker IPK / Web-Based Management, depending on the
> firmware). Port 502 is used by the controller's own Modbus TCP slave; to avoid a
> conflict, map the container to another port, for example `-p 1502:502`.

---

## 1. Copy the tar file to the target machine

Use a USB stick, `scp` or WinSCP, for example:

```bash
scp modbus-server.tar user@<target-ip>:/home/user/
```

## 2. Load the image

```bash
docker load -i modbus-server.tar
```

Expected output:

```
Loaded image: modbus-server:latest
```

To check that the image is there:

```bash
docker images modbus-server
```

## 3. Start the container

### Option A – Default settings (port 502 on all network interfaces)

```bash
docker run -d \
  --name modbus-server \
  --restart unless-stopped \
  -p 502:502 \
  modbus-server:latest
```

### Option B – Different IP address and/or port

**Do not put the external IP address in the config file.** Inside the container, the
server must always listen on `host = 0.0.0.0`, `port = 502`. Choose the external
IP address and port in the `-p` mapping instead:

```
-p <host-ip>:<host-port>:502
```

Example: clients connect to `192.168.178.200`, port `1502`:

```bash
docker run -d \
  --name modbus-server \
  --restart unless-stopped \
  -p 192.168.178.200:1502:502 \
  modbus-server:latest
```

`192.168.178.200` must be an IP address of the target machine itself (check with `ip addr`).

> If you set `host = 192.168.178.200` in `modbus_server_config.ini`, the server fails with
> `[Errno 99] cannot assign requested address`. The container has its own internal IP
> address, so the host's IP address does not exist inside the container.

### Option C – Own tag list and parameter file (without rebuilding)

Put your own `modbus_tags.csv` and `modbus_server_config.ini` in a folder on the
target machine, go to that folder, and run:

```bash
docker run -d \
  --name modbus-server \
  --restart unless-stopped \
  -p 502:502 \
  -v $(pwd)/modbus_server_config.ini:/app/modbus_server_config.ini \
  -v $(pwd)/modbus_tags.csv:/app/modbus_tags.csv \
  modbus-server:latest
```

After you change these files, restart the container: `docker restart modbus-server`.

## 4. Check that it works

```bash
docker ps --filter name=modbus-server
docker logs -f modbus-server
```

The log should show:

```
INFO Loaded 2 tags from /app/modbus_tags.csv
INFO Starting Modbus TCP server on 0.0.0.0:502 (unit ids: 1)
INFO Server listening.
```

Then connect with a Modbus TCP client (for example Modbus Poll, QModMaster or a PLC):

| Setting       | Value                                           |
|---------------|-------------------------------------------------|
| IP address    | IP address of the target machine                |
| Port          | 502 (or the host port you chose in `-p`)        |
| Unit/Slave ID | 1                                               |
| Registers     | ActualValue = HR 0–1 (float32), Setpoint = HR 10 (int16) |

Every write by a client is shown in the log, for example:

```
INFO Write Setpoint             value=42 (raw 42) -> holding register 10, unit 1
```

## 5. Manage the container

| Action          | Command                                              |
|-----------------|------------------------------------------------------|
| Stop            | `docker stop modbus-server`                          |
| Start           | `docker start modbus-server`                         |
| Restart         | `docker restart modbus-server`                       |
| Remove          | `docker rm -f modbus-server`                         |
| Install update  | `docker rm -f modbus-server`, `docker load -i modbus-server.tar`, then step 3 again |

## Troubleshooting

| Symptom                                       | Cause / solution |
|-----------------------------------------------|------------------|
| `Errno 99 cannot assign requested address`    | `host` in the config is not `0.0.0.0`. Set `host = 0.0.0.0` and choose the IP in `-p` (see 3B). |
| `port is already allocated` on `docker run`   | Another program or container already uses this port. Choose another host port, e.g. `-p 1502:502`. |
| `exec format error` in the log, or the warning `The requested image's platform (linux/amd64) does not match the detected host platform` | Wrong CPU architecture (amd64 image on ARM). Check with `uname -m` and build the image for the correct platform (see section 0). |
| Client gets no answer                         | Check the firewall on the target machine, the port in `-p`, and the unit id (only unit ids from the tag file answer). |
