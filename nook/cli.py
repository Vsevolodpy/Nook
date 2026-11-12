"""CLI для разработки и тестов — пользователю нужен только .exe с окном."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .model.library import Library, serialize
from .model.config import Settings


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="nook", description="Nook — быстрое хранилище документов")
    parser.add_argument("--data-dir", help="каталог данных (по умолчанию %%APPDATA%%\\nook)")
    sub = parser.add_subparsers(dest="command")

    gui = sub.add_parser("gui", help="открыть окно (по умолчанию)")
    gui.add_argument("--debug", action="store_true", help="отладка webview")

    add = sub.add_parser("add", help="добавить файлы в зону")
    add.add_argument("paths", nargs="+")
    add.add_argument("-t", "--tag", action="append", default=[], help="тег (можно несколько)")
    add.add_argument("-n", "--note", default=None)
    add.add_argument("--move", action="store_true", help="переместить, а не копировать")
    add.add_argument("--json", action="store_true")

    search = sub.add_parser("search", help="поиск по зоне")
    search.add_argument("query", nargs="?", default="")
    search.add_argument("--limit", type=int, default=50)
    search.add_argument("--json", action="store_true")

    sub.add_parser("list", help="все файлы")
    sub.add_parser("stats", help="статистика зоны")

    tags = sub.add_parser("tags", help="список тегов")
    tags.add_argument("--json", action="store_true")

    tag = sub.add_parser("tag", help="повесить тег на файлы")
    tag.add_argument("tag")
    tag.add_argument("ids", nargs="+", type=int)
    tag.add_argument("--remove", action="store_true")

    delete = sub.add_parser("delete", help="в корзину")
    delete.add_argument("ids", nargs="+", type=int)

    restore = sub.add_parser("restore", help="из корзины обратно")
    restore.add_argument("ids", nargs="+", type=int)

    open_cmd = sub.add_parser("open", help="открыть файл из зоны")
    open_cmd.add_argument("id", type=int)

    export = sub.add_parser("export", help="экспорт зоны в zip")
    export.add_argument("--out", default=None)

    sub.add_parser("vault", help="показать/открыть папку зоны")

    return parser


def _print_items(items, as_json: bool) -> None:
    if as_json:
        print(json.dumps(items, ensure_ascii=False, indent=2))
        return
    for item in items:
        tags = " ".join(f"#{tag}" for tag in item["tags"])
        print(f"{item['id']:>4}  {item['name']}  {item['added_at_human']}  {item['size_human']}  {tags}".rstrip())


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    command = args.command or "gui"

    if command == "gui":
        from .controller.main import run

        run(debug=getattr(args, "debug", False))
        return 0

    settings = Settings.load(Path(args.data_dir) / "config.json") if args.data_dir else Settings.load()
    library = Library(settings)

    try:
        if command == "add":
            if args.move:
                settings.copy_mode = "move"
            result = library.add_paths(args.paths, args.tag, args.note, source="cli")
            if args.json:
                print(json.dumps(result, ensure_ascii=False, indent=2))
            else:
                for name in result["added"]:
                    print(f"+ {name}")
                for message in result["duplicates"]:
                    print(f"= {message}")
                for message in result["errors"]:
                    print(f"! {message}", file=sys.stderr)
            return 0 if not result["errors"] else 1

        if command == "search":
            payload = library.search(args.query, args.limit)
            if args.json:
                print(json.dumps(payload, ensure_ascii=False, indent=2))
            else:
                _print_items(payload["items"], False)
                print(f"— {len(payload['items'])} из {payload['total']} за {payload['took_ms']} мс")
            return 0

        if command == "list":
            _print_items([serialize(record) for record in library.index.snapshot()], False)
            return 0

        if command == "stats":
            print(json.dumps(library.stats(), ensure_ascii=False, indent=2))
            return 0

        if command == "tags":
            tags = library.tags.list()
            if args.json:
                print(json.dumps(tags, ensure_ascii=False, indent=2))
            else:
                for item in tags:
                    print(f"#{item['name']}  ({item['count']})")
            return 0

        if command == "tag":
            if args.remove:
                result = library.unassign_tag(args.ids, args.tag)
            else:
                result = library.assign_tag(args.ids, args.tag)
            print(json.dumps(result, ensure_ascii=False))
            return 0 if result.get("ok") else 1

        if command == "delete":
            print(json.dumps(library.delete(args.ids), ensure_ascii=False))
            return 0

        if command == "restore":
            print(json.dumps(library.restore(args.ids), ensure_ascii=False))
            return 0

        if command == "open":
            ok, error = library.zone.open(args.id)
            if not ok:
                print(error, file=sys.stderr)
            return 0 if ok else 1

        if command == "export":
            path = library.zone.export_zip(args.out)
            print(path)
            return 0

        if command == "vault":
            print(library.settings.vault_dir)
            return 0
    finally:
        library.close()

    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
