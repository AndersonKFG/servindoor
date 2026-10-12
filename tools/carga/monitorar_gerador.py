"""Observa o gerador local sem ler argumentos, ambiente, credenciais ou payloads."""

import collections
import datetime
import json
from pathlib import Path
import subprocess
import sys
import time


def docker(*arguments):
    result = subprocess.run(
        ['docker', *arguments], capture_output=True, text=True, timeout=8,
    )
    return result.stdout.strip() if result.returncode == 0 else ''


def memory():
    fields = {}
    for line in Path('/proc/meminfo').read_text().splitlines():
        name, value = line.split(':', 1)
        if name in {'MemTotal', 'MemAvailable', 'SwapTotal', 'SwapFree'}:
            fields[name + '_kb'] = int(value.split()[0])
    return fields


def connections(container):
    # Namespace de rede do gerador, compartilhado com o host do daemon Docker.
    # Registra apenas contagens por estado; não grava IPs nem conteúdo de tráfego.
    states = collections.Counter()
    labels = {'01': 'established', '02': 'syn_sent', '03': 'syn_recv',
              '06': 'time_wait', '08': 'close_wait', '0A': 'listen'}
    table = docker('exec', container, 'cat', '/proc/net/tcp', '/proc/net/tcp6')
    for line in table.splitlines():
        fields = line.split()
        if not fields or not fields[0].rstrip(':').isdigit():
            continue
        remote_port = int(fields[2].split(':')[1], 16)
        if remote_port in (80, 443):
            states[labels.get(fields[3], fields[3])] += 1
    return dict(states)


def processes(container):
    # O daemon Docker pode usar outro namespace de PIDs. Leia /proc dentro do
    # container para observar o mesmo processo que gera a carga.
    command = '''
for process in /proc/[0-9]*; do
    read -r comm < "$process/comm" 2>/dev/null || continue
    case "$comm" in
        k6*)
            printf 'pid: %s\\n' "${process##*/}"
            set -- "$process"/fd/*
            printf 'open_fds: %s\\n' "$#"
            awk '/^(VmRSS|VmSwap|Threads):/ {print $1, $2}
                 /^Max open files/ {print "fd_limits:", $4, $5}' "$process/status" "$process/limits"
            printf 'end\\n'
            ;;
    esac
done
'''
    result = []
    process = {}
    for line in docker('exec', container, 'sh', '-c', command).splitlines():
        if line == 'end':
            if process:
                result.append(process)
            process = {}
            continue
        name, separator, value = line.partition(':')
        if separator and name in {'pid', 'open_fds', 'VmRSS', 'VmSwap', 'Threads', 'fd_limits'}:
            process[name] = value.split() if name == 'fd_limits' else int(value.strip())
    return result


def main(container, output):
    started = False
    deadline = time.monotonic() + 60
    with Path(output).open('w', encoding='utf-8', buffering=1) as destination:
        while True:
            try:
                running = docker('inspect', '--format', '{{.State.Running}}', container) == 'true'
                if not running:
                    if started or time.monotonic() >= deadline:
                        return
                    time.sleep(1)
                    continue
                started = True
                statistics = docker('stats', '--no-stream', '--format', '{{json .}}', container)
                sample = {
                    'utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
                    'docker': json.loads(statistics) if statistics else None,
                    'wsl_memory': memory(), 'generator_tcp_web': connections(container),
                    'k6': processes(container),
                }
            except (OSError, ValueError, subprocess.TimeoutExpired) as error:
                sample = {'monitor_error': type(error).__name__}
            destination.write(json.dumps(sample) + '\n')
            time.sleep(2)


if __name__ == '__main__':
    main(sys.argv[1], sys.argv[2])
