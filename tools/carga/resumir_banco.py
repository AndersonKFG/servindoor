"""Resume a coleta do PostgreSQL no console, sem dependências externas."""
import csv
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path


def main():
    pasta = Path(__file__).resolve().parent / "resultados"
    arquivos = list(pasta.glob("banco_*.csv"))
    if len(sys.argv) > 1:
        arquivo = Path(sys.argv[1])
    elif arquivos:
        arquivo = max(arquivos, key=lambda p: p.stat().st_mtime_ns)
    else:
        raise SystemExit("Nenhum banco_*.csv encontrado. Execute o monitor durante a carga.")
    with arquivo.open(newline="", encoding="utf-8") as entrada:
        leitor = csv.DictReader(entrada)
        colunas = [
            "instante_utc", "pid", "state", "wait_event_type", "wait_event",
            "transacao_ms", "consulta_ms", "bloqueadores", "operacao",
        ]
        if not set(colunas).issubset(leitor.fieldnames or []):
            raise SystemExit("CSV sem as colunas esperadas do monitor.")
        # Uma linha incompleta pode ocorrer se a coleta ainda estiver escrevendo.
        linhas = [r for r in leitor if all(r.get(c) is not None for c in colunas)]
    print(f"Arquivo: {arquivo.name}\nObservações de conexões: {len(linhas)}")
    if not linhas:
        print("A coleta não registrou conexões ativas/em transação.")
        return
    print(f"Intervalo UTC: {linhas[0]['instante_utc']} até {linhas[-1]['instante_utc']}")
    print("\nEstados mais frequentes (observações repetidas, não requisições):")
    frequencias = Counter(tuple(r[c] for c in ("state", "wait_event_type", "wait_event", "operacao")) for r in linhas)
    for chave, quantidade in frequencias.most_common(10):
        print(f"{quantidade:>6} | " + " | ".join(v or "-" for v in chave))

    por_pid = defaultdict(list)
    for r in linhas:
        r["_instante"] = datetime.fromisoformat(r["instante_utc"])
        por_pid[r["pid"]].append(r)
    def idade(r):
        return float(r["transacao_ms"] or 0)
    def bloqueadores(r):
        return [p.strip() for p in r["bloqueadores"].strip("{}").split(",") if p.strip()]
    def exibir(rotulo, r):
        print(rotulo + " | " + " | ".join(f"{c}={r[c] or '-'}" for c in colunas))

    print("\nMaiores transações bloqueadas e suas cadeias de bloqueadores:")
    vistos = set()
    casos = 0
    for r in sorted(linhas, key=idade, reverse=True):
        if not bloqueadores(r) or r["pid"] in vistos:
            continue
        vistos.add(r["pid"])
        casos += 1
        exibir("ESPERANDO", r)
        pendentes = bloqueadores(r)
        cadeia = {r["pid"]}
        while pendentes and len(cadeia) < 10:
            pid = pendentes.pop(0)
            if pid in cadeia:
                continue
            cadeia.add(pid)
            candidatos = por_pid.get(pid, [])
            if not candidatos:
                print(f"BLOQUEADOR | pid={pid} | sem observação capturada")
                continue
            proximo = min(candidatos, key=lambda x: abs((x["_instante"] - r["_instante"]).total_seconds()))
            # O CSV antigo usa clock_timestamp por linha: aceita somente uma
            # observação próxima para não misturar transações de outras coletas.
            if abs((proximo["_instante"] - r["_instante"]).total_seconds()) > 1:
                print(f"BLOQUEADOR | pid={pid} | sem observação na mesma coleta")
                continue
            exibir("BLOQUEADOR", proximo)
            pendentes.extend(bloqueadores(proximo))
        if casos >= 5:
            break
    if not casos:
        print("Nenhum bloqueador registrado nas amostras.")
    print("\nMaiores transações observadas (duração inclui espera):")
    for r in sorted(linhas, key=idade, reverse=True)[:5]:
        exibir("TRANSACAO", r)
    print("\nAmostragem não cobre a fila do pool nem toda a latência HTTP.")


if __name__ == "__main__":
    main()
