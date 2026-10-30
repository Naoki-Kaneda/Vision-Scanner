"""
detect-secrets でリポジトリを走査し、.secrets.baseline に記録済みの候補を除いた「新しい候補」を数える。

CI（ci.yml）と週次スキャン（secrets-scan.yml）の両方から使う。除外条件をここ1か所にまとめ、
.secrets.baseline の作成時・.pre-commit-config.yaml とずれないようにする（ずれると誤検知が出続ける）。

記録済みかどうかは (ファイル名, ハッシュ) で照合し、行番号は見ない。pre-commit のフックは行番号まで
照合するため、記録済みのファイルに1行足すだけで失敗する。CI でそれを避けるためにこの照合を使う。

使い方: python .github/scripts/find_new_secrets.py [結果の出力先.json]
標準出力に新しい候補の件数、標準エラーに候補の一覧を出す。結果のファイルには新しい候補だけを書く。
"""

import json
import subprocess  # nosec B404 -- 自分の Python で detect-secrets を起動するだけ
import sys

BASELINE = ".secrets.baseline"
# .secrets.baseline の作成時・.pre-commit-config.yaml の exclude とそろえる
EXCLUDE_FILES = [
    r"\.lock$",
    r"\.txt$",
    r"\.secrets\.baseline$",
    r"package-lock\.json$",
    r"venv/",
    r"\.venv/",
]


def normalize(filename: str) -> str:
    """Windows で作ったベースラインは区切りが \\ になるので / にそろえる。"""
    return filename.replace("\\", "/")


def main() -> int:
    output = sys.argv[1] if len(sys.argv) > 1 else ".secrets-scan-result.json"

    command = [sys.executable, "-m", "detect_secrets", "scan"]
    for pattern in EXCLUDE_FILES:
        command += ["--exclude-files", pattern]
    # 引数はこのファイルの定数だけで組み立て、シェルも通さない
    result = subprocess.run(command, check=True, capture_output=True, text=True)  # nosec B603
    scan = json.loads(result.stdout)

    with open(BASELINE, encoding="utf-8") as f:
        known = {
            (normalize(name), secret["hashed_secret"])
            for name, secrets in json.load(f)["results"].items()
            for secret in secrets
        }

    new_results = {}
    for name, secrets in scan.get("results", {}).items():
        new = [s for s in secrets if (normalize(name), s["hashed_secret"]) not in known]
        if new:
            new_results[normalize(name)] = new
    scan["results"] = new_results

    with open(output, "w", encoding="utf-8") as f:
        json.dump(scan, f, ensure_ascii=False, indent=2)

    for name, secrets in new_results.items():
        for s in secrets:
            print(f"新しい候補: {name}:{s['line_number']}（{s['type']}）", file=sys.stderr)
    print(sum(len(v) for v in new_results.values()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
