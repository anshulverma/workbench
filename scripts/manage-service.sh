#!/bin/bash
# Workbench service management script.
#
# Usage:
#   workbench start       — start the service
#   workbench stop        — stop the service
#   workbench restart     — restart the service
#   workbench status      — show service status
#   workbench logs        — tail logs (Ctrl+C to stop)
#   workbench logs -n 50  — show last 50 log lines
#   workbench install     — install the systemd service (run once)
#   workbench uninstall   — remove the systemd service
#   workbench health      — check the /health endpoint

set -e

SERVICE_NAME="workbench"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
SERVICE_FILE="$HOME/.config/systemd/user/$SERVICE_NAME.service"

source "$SCRIPT_DIR/workbench-env.sh" 2>/dev/null || true

cmd_install() {
    mkdir -p "$HOME/.config/systemd/user"
    cat > "$SERVICE_FILE" << EOF
[Unit]
Description=Workbench Intelligence Feed Server
After=network.target

[Service]
Type=simple
WorkingDirectory=$PROJECT_DIR
ExecStart=$SCRIPT_DIR/workbench-start.sh
Restart=on-failure
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=default.target
EOF
    systemctl --user daemon-reload
    systemctl --user enable "$SERVICE_NAME"
    echo "Installed and enabled $SERVICE_NAME service."
    echo "Run 'workbench start' to start it."
}

cmd_uninstall() {
    systemctl --user stop "$SERVICE_NAME" 2>/dev/null || true
    systemctl --user disable "$SERVICE_NAME" 2>/dev/null || true
    rm -f "$SERVICE_FILE"
    systemctl --user daemon-reload
    echo "Uninstalled $SERVICE_NAME service."
}

cmd_start() {
    systemctl --user start "$SERVICE_NAME"
    echo "Started $SERVICE_NAME."
    sleep 2
    cmd_health
}

cmd_stop() {
    systemctl --user stop "$SERVICE_NAME"
    echo "Stopped $SERVICE_NAME."
}

cmd_restart() {
    systemctl --user restart "$SERVICE_NAME"
    echo "Restarted $SERVICE_NAME."
    sleep 2
    cmd_health
}

cmd_status() {
    systemctl --user status "$SERVICE_NAME" --no-pager
}

cmd_logs() {
    local logfile="$PROJECT_DIR/logs/workbench.log"
    if [ ! -f "$logfile" ]; then
        echo "No log file yet at $logfile"
        return 1
    fi
    if [ "$1" = "-n" ] && [ -n "$2" ]; then
        tail -n "$2" "$logfile"
    else
        tail -f "$logfile"
    fi
}

cmd_health() {
    local url="http://localhost:${WORKBENCH_PORT:-8421}/health"
    if curl -s --max-time 3 "$url" 2>/dev/null | grep -q '"ok"'; then
        echo "✓ Healthy: $url"
    else
        echo "✗ Unhealthy or unreachable: $url"
        return 1
    fi
}

cmd_help() {
    echo "Usage: workbench <command>"
    echo ""
    echo "Commands:"
    echo "  install     Install the systemd user service (run once)"
    echo "  uninstall   Remove the systemd user service"
    echo "  start       Start the service"
    echo "  stop        Stop the service"
    echo "  restart     Restart the service"
    echo "  status      Show service status"
    echo "  logs        Tail logs (Ctrl+C to stop)"
    echo "  logs -n N   Show last N log lines"
    echo "  health      Check the /health endpoint"
}

case "${1:-help}" in
    install)   cmd_install ;;
    uninstall) cmd_uninstall ;;
    start)     cmd_start ;;
    stop)      cmd_stop ;;
    restart)   cmd_restart ;;
    status)    cmd_status ;;
    logs)      shift; cmd_logs "$@" ;;
    health)    cmd_health ;;
    help|*)    cmd_help ;;
esac
