#!/bin/bash
# =============================================================================
# Kafka Agent Stack — Install Script
# Kafka 4.2.0 (KRaft) + Kafka Connect + ksqlDB 0.29.0 + PostgreSQL (source)
# Target: Fedora / RHEL / CentOS
# =============================================================================

set -euo pipefail

# ---------- VERSIONS ----------
KAFKA_VERSION="4.2.0"
KAFKA_SCALA="2.13"
KSQLDB_VERSION="0.29.0"


# ---------- PATHS ----------
INSTALL_DIR="/opt/kafka-stack"
KAFKA_DIR="$INSTALL_DIR/kafka"
KSQLDB_DIR="$INSTALL_DIR/ksqldb"
CONNECT_PLUGINS_DIR="$INSTALL_DIR/connect-plugins"
LOGS_DIR="/var/log/kafka-stack"
DATA_DIR="/var/data/kafka-stack"

# ---------- COLORS ----------
GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'
info()  { echo -e "${GREEN}[INFO]${NC}  $1"; }
warn()  { echo -e "${YELLOW}[WARN]${NC}  $1"; }
error() { echo -e "${RED}[ERROR]${NC} $1"; exit 1; }

# ---------- PRE-FLIGHT ----------
[[ $EUID -ne 0 ]] && error "Run as root or with sudo"

info "Checking Java..."
if ! command -v java &>/dev/null; then
  info "Installing Java 21 (required for Kafka 4.x)..."
  dnf install -y java-21-openjdk-devel
fi

JAVA_VER=$(java -version 2>&1 | awk -F '"' '/version/ {print $2}' | cut -d'.' -f1)
[[ "$JAVA_VER" -lt 17 ]] && error "Kafka 4.x requires Java 17+. Found Java $JAVA_VER."
info "Java $JAVA_VER — OK"

# Install utilities
dnf install -y curl wget unzip tar nc file postgresql postgresql-server 2>/dev/null || true

# ---------- DIRECTORY SETUP ----------
info "Creating directories..."
mkdir -p "$KAFKA_DIR" "$KSQLDB_DIR" "$CONNECT_PLUGINS_DIR"
mkdir -p "$LOGS_DIR"/{kafka,connect,ksqldb}
mkdir -p "$DATA_DIR"/{kafka-logs,ksqldb-state}

# ---------- KAFKA ----------
KAFKA_TAR="kafka_${KAFKA_SCALA}-${KAFKA_VERSION}.tgz"
KAFKA_URL="https://downloads.apache.org/kafka/${KAFKA_VERSION}/${KAFKA_TAR}"

if [[ ! -d "$KAFKA_DIR/bin" ]]; then
  info "Downloading Kafka $KAFKA_VERSION..."
  wget -q --show-progress "$KAFKA_URL" -O "/tmp/$KAFKA_TAR"
  tar -xzf "/tmp/$KAFKA_TAR" -C "$KAFKA_DIR" --strip-components=1
  rm "/tmp/$KAFKA_TAR"
  info "Kafka extracted to $KAFKA_DIR"
else
  info "Kafka already installed — skipping download"
fi

# ---------- KSQLDB ----------
KSQLDB_TAR="ksqldb-${KSQLDB_VERSION}.tar.gz"
KSQLDB_URL="https://packages.confluent.io/archive/7.6/confluent-community-7.6.0.tar.gz"

# ksqlDB standalone is shipped inside Confluent Community — extract only ksqldb
if [[ ! -d "$KSQLDB_DIR/bin" ]]; then
  info "Downloading ksqlDB (via Confluent Community $KSQLDB_VERSION)..."
  warn "This is ~500MB — includes ksqlDB + dependencies"
  wget -q --show-progress \
    "https://packages.confluent.io/archive/7.6/confluent-community-7.6.0.tar.gz" \
    -O "/tmp/confluent-community.tar.gz"
  tar -xzf "/tmp/confluent-community.tar.gz" -C "$KSQLDB_DIR" --strip-components=1
  rm "/tmp/confluent-community.tar.gz"
  info "ksqlDB extracted to $KSQLDB_DIR"
else
  info "ksqlDB already installed — skipping download"
fi

# ---------- JDBC CONNECTOR PLUGIN ----------
# Downloaded as a ZIP from Confluent Hub API — includes connector JAR + all deps.
# PostgreSQL JDBC driver is bundled inside; no separate download needed.
JDBC_HUB_URL="https://api.hub.confluent.io/api/plugins/confluentinc/kafka-connect-jdbc/versions/latest/archive"
JDBC_PLUGIN_DIR="$CONNECT_PLUGINS_DIR/kafka-connect-jdbc"

if [[ ! -d "$JDBC_PLUGIN_DIR/lib" ]]; then
  info "Downloading JDBC Connector plugin from Confluent Hub..."
  mkdir -p "$JDBC_PLUGIN_DIR"
  wget -q --show-progress "$JDBC_HUB_URL" -O "/tmp/kafka-connect-jdbc.zip"

  # Verify it's actually a zip (not an HTML error page)
  if ! file "/tmp/kafka-connect-jdbc.zip" | grep -q "Zip"; then
    error "JDBC connector download failed — got: $(file /tmp/kafka-connect-jdbc.zip)"
  fi

  # The ZIP extracts to confluentinc-kafka-connect-jdbc-<version>/lib/*.jar
  unzip -q "/tmp/kafka-connect-jdbc.zip" -d "/tmp/jdbc-extract/"
  EXTRACTED_DIR=$(find /tmp/jdbc-extract -maxdepth 1 -type d -name "confluentinc-*" | head -1)
  cp -r "$EXTRACTED_DIR/." "$JDBC_PLUGIN_DIR/"
  rm -rf "/tmp/kafka-connect-jdbc.zip" "/tmp/jdbc-extract/"

  info "JDBC connector installed at $JDBC_PLUGIN_DIR"
  info "  JARs: $(ls "$JDBC_PLUGIN_DIR/lib/" | wc -l) files"
else
  info "JDBC connector already installed — skipping"
fi

# ---------- POSTGRESQL SETUP ----------
info "Setting up PostgreSQL..."
if ! systemctl is-active --quiet postgresql; then
  postgresql-setup --initdb 2>/dev/null || true
  systemctl enable --now postgresql
fi

# Create source DB + user + table for testing
sudo -u postgres psql <<'SQL' 2>/dev/null || warn "Postgres setup already done or failed — check manually"
  CREATE USER kafka_user WITH PASSWORD 'kafka_pass';
  CREATE DATABASE kafka_source OWNER kafka_user;
  \c kafka_source
  GRANT ALL PRIVILEGES ON DATABASE kafka_source TO kafka_user;
  CREATE TABLE IF NOT EXISTS orders (
    id          SERIAL PRIMARY KEY,
    customer_id INT NOT NULL,
    product     VARCHAR(255),
    amount      DECIMAL(10,2),
    status      VARCHAR(50) DEFAULT 'pending',
    created_at  TIMESTAMP DEFAULT NOW(),
    updated_at  TIMESTAMP DEFAULT NOW()
  );
  GRANT ALL PRIVILEGES ON TABLE orders TO kafka_user;
  GRANT USAGE, SELECT ON SEQUENCE orders_id_seq TO kafka_user;
SQL

info "PostgreSQL ready — DB: kafka_source, User: kafka_user"

# ---------- SYMLINKS FOR CONVENIENCE ----------
ln -sf "$KAFKA_DIR/bin/kafka-topics.sh"          /usr/local/bin/kafka-topics      2>/dev/null || true
ln -sf "$KAFKA_DIR/bin/kafka-console-producer.sh" /usr/local/bin/kafka-producer   2>/dev/null || true
ln -sf "$KAFKA_DIR/bin/kafka-console-consumer.sh" /usr/local/bin/kafka-consumer   2>/dev/null || true
ln -sf "$KSQLDB_DIR/bin/ksql"                     /usr/local/bin/ksql             2>/dev/null || true

# ---------- DONE ----------
echo ""
info "=============================================="
info " Install complete. Next steps:"
info "  1. Run: sudo bash scripts/init-kraft.sh    (format KRaft storage)"
info "  2. Run: sudo bash scripts/start.sh         (start all services)"
info "  3. Check: sudo bash scripts/status.sh      (verify all running)"
info "=============================================="
echo ""
info "Service ports:"
info "  Kafka broker    : localhost:9092"
info "  Kafka Connect   : localhost:8083"
info "  ksqlDB          : localhost:8088"
info "  PostgreSQL      : localhost:5432"
