"""Verifica os volumes antes de carregar os segredos e iniciar a API."""
import os
import sys
from pathlib import Path
from tempfile import TemporaryFile


def conferir_volume(variavel: str) -> Path:
    pasta = Path(os.environ[variavel])
    try:
        with TemporaryFile(dir=pasta):
            pass
    except OSError as exc:
        raise SystemExit(
            f"Nexus: sem acesso de escrita a {variavel} ({pasta}) com UID:GID "
            f"{os.geteuid()}:{os.getegid()}. Confira o volume e suas permissões. {exc.strerror}"
        ) from exc
    return pasta


def main() -> None:
    if os.geteuid() == 0:
        raise SystemExit("Nexus: execute a API com o usuário dedicado da imagem.")

    segredos = conferir_volume("NEXUS_SEGREDOS_DIR")
    for arquivo in segredos.glob("*.txt"):
        try:
            with arquivo.open("rb"):
                pass
        except OSError as exc:
            raise SystemExit(
                f"Nexus: sem acesso a {arquivo.name} no volume de segredos. "
                "Execute o ajuste de permissões dos volumes antes de atualizar."
            ) from exc
    conferir_volume("MEDIA_DIR")
    conferir_volume("BACKUP_DIR")
    os.execvp(sys.argv[1], sys.argv[1:])


if __name__ == "__main__":
    main()
