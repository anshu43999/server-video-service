"""Summarize ONLY M111/T02 and M112/T02 historical runner output; never delete.

The Markdown inventory is consumed by the separately reviewed recycle action.
No recursive database, APK, source, deployment or screenshot cleanup.
"""
import argparse
import hashlib
import json
from pathlib import Path

from test_report_retention import atomic_markdown, safe_text, summarize_log, upsert_run

ROOT = Path(__file__).resolve().parents[1]


def migrate(major, prefix):
    evidence = ROOT / f'harness/evidence/{major}/T02'
    report = evidence / 'TEST_REPORT.md'
    marker = '<!-- historical-log-inventory-20261112 -->'
    if report.exists() and marker in report.read_text(encoding='utf-8'):
        raise ValueError('Migration already summarized; no report or source was changed')
    candidates, results, unknown = {}, {}, []
    runtimes = sorted((ROOT / '.tmp').glob(prefix + '*'))
    for runtime in runtimes:
        if not runtime.is_dir() or runtime.is_symlink():
            continue
        if (runtime / 'pg-data/postmaster.pid').exists():
            raise RuntimeError(f'Active PID marker: {runtime}')
        for path in runtime.glob('*.log'):
            candidates[path] = None
        result_path = runtime / 'result.json'
        if result_path.exists():
            results[result_path] = json.loads(result_path.read_text(encoding='utf-8'))
    # Exact historical result/log paths only; no recursive sweep of arbitrary evidence.
    for path in evidence.glob('*result.json'):
        results[path] = json.loads(path.read_text(encoding='utf-8'))
    for archive in (evidence / 'runs').glob(prefix + '*'):
        if archive.is_symlink():
            raise RuntimeError(f'Link: {archive}')
        for path in archive.glob('*.log'):
            candidates[path] = None
        path = archive / 'result.json'
        if path.exists():
            results[path] = json.loads(path.read_text(encoding='utf-8'))
    # M112 backend-final includes renamed followups whose summaries remain separate.
    for path in (evidence / 'backend-final').glob('*.log'):
        candidates[path] = None
    seen, groups = {}, {}
    for path, result in results.items():
        run_id = Path(result['runtime']).name
        if not run_id.startswith(prefix):
            raise ValueError(f'Unexpected result scope: {path}')
        # Do not discard inconsistent copies of one run.
        signature = json.dumps({k: v for k, v in result.items() if k not in ('archivedResult',)}, sort_keys=True)
        normalized = json.loads(signature)
        for row in normalized.get('tests', []):
            row.pop('archivedLog', None)
        signature = json.dumps(normalized, sort_keys=True)
        if run_id in seen and seen[run_id] != signature:
            raise ValueError(f'Conflicting historical results: {run_id}')
        seen[run_id] = signature
        groups[run_id] = result
        candidates[path] = None
    for path in candidates:
        if path.is_symlink() or not path.is_file():
            raise ValueError(f'Unsafe candidate: {path}')
        # resolve containment before reading; only local task scope.
        resolved = path.resolve()
        if not resolved.is_relative_to(ROOT.resolve()):
            raise ValueError(f'Outside root: {path}')
        data = path.read_bytes()
        candidates[path] = (len(data), hashlib.sha256(data).hexdigest())
    for run_id, result in sorted(groups.items()):
        summaries = {}
        for row in result.get('tests', []):
            options = [Path(row['log'])]
            if row.get('archivedLog'):
                options.append(ROOT / row['archivedLog'])
            options += [evidence / 'runs' / run_id / Path(row['log']).name]
            path = next((p for p in options if p in candidates and p.suffix == '.log'), None)
            if path:
                summaries[row['pattern']] = summarize_log(path)
        result['cleanup'] = '历史日志已摘要化；回收状态见文末迁移清单，不代表重新执行了测试'
        upsert_run(report, f'{major}后端回归', result, summaries)
    content = report.read_text(encoding='utf-8')
    if marker in content:
        raise ValueError('Migration already summarized; inspect report instead of repeating')
    lines = [marker, '## 2026-11-12 历史原始材料迁移', '',
             '本节只归档测试事实和文件定位摘要，不包含完整日志。未重跑原业务测试；旧版本、环境缺失项仍未知。缺少result.json的中断轮次只记录可观察日志结束状态，不能据此补记整轮通过。', '',
             '状态：摘要已生成并回读，待核验后回收精确清单。历史隔离数据库目录、图片、业务数据及其他任务输出不在本次清单内。', '',
             '### 独立日志核验（包含中断、失败及重复副本）', '',
             '| 原相对路径 | 执行数 | 结束标记 |', '|---|---:|---|']
    for path in sorted(candidates):
        if path.suffix != '.log':
            continue
        summary = summarize_log(path)
        lines.append(f"| {path.relative_to(ROOT).as_posix()} | {summary['ran'] if summary['ran'] is not None else '未知'} | {safe_text(summary['terminal'])} |")
        for reason in summary['failures'] + summary['causes'] + summary['skipReasons']:
            unknown.append(f'- `{path.relative_to(ROOT).as_posix()}`：{reason}')
    lines += ['', '### 失败/跳过/初始化异常摘要', ''] + (unknown or ['未提取到额外异常；不能据此认定无异常。'])
    lines += ['', '### 回收精确清单', '',
              'SHA256为原文件内容摘要，仅用于迁移前一致性校验，不等价于保留日志。原路径作为历史标识，不是仍存在的附件链接。', '',
              '| 原相对路径 | 字节数 | SHA256 |', '|---|---:|---|']
    for path, (size, digest) in sorted(candidates.items()):
        lines.append(f'| {path.relative_to(ROOT).as_posix()} | {size} | {digest} |')
    atomic_markdown(report, content.rstrip() + '\n\n' + '\n'.join(lines) + '\n')
    return {'report': str(report), 'runs': len(groups), 'files': len(candidates),
            'bytes': sum(size for size, _ in candidates.values())}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--scope', choices=['M111', 'M112'], required=True)
    args = parser.parse_args()
    print(json.dumps(migrate(args.scope, {'M111': 'm111-updates-', 'M112': 'm112-lifecycle-'}[args.scope]), ensure_ascii=False))
