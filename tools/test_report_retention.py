"""Single Markdown report, temporary diagnostics; no business database access."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import platform
import re
import shutil
import stat
import subprocess
import tempfile


def safe_text(value):
    value = str(value)
    value = re.sub(r'(https?://|postgresql(?:\+\w+)?://)[^/\s@]+@', r'\1[redacted]@', value)
    value = re.sub(r'(?i)(authorization|password|token|secret)([=:]\s*)[^\s,;]+', r'\1\2[redacted]', value)
    return value.replace('|', r'|').replace('\r', ' ').replace('\n', ' ')


def summarize_log(path):
    """Keep counters, test failure identities and short causes, never raw output."""
    path = Path(path)
    raw = path.read_bytes()
    content = raw.decode('utf-8', errors='replace')
    runs = re.findall(r'^Ran (\d+) tests? in ([\d.]+)s', content, re.M)
    endings = re.findall(r'^(?:OK(?: \([^\n]*\))?|FAILED \([^\n]*\))\s*$', content, re.M)
    counts = {name: int(re.search(rf'{name}=(\d+)', endings[-1]).group(1))
              if endings and re.search(rf'{name}=(\d+)', endings[-1]) else 0
              for name in ('failures', 'errors', 'skipped', 'expected failures', 'unexpected successes')}
    ran = int(runs[-1][0]) if runs else None
    issues = re.findall(r'^(?:FAIL|ERROR): .+$', content, re.M)
    causes = re.findall(r'^(?:[\w.]+(?:Error|Exception)|AssertionError|FAILED|FATAL|PANIC):?[^\n]*$', content, re.M)
    skipped = re.findall(r'^test[^\n]* \.{3} skipped [^\n]*$', content, re.M)
    return dict(ran=ran, seconds=runs[-1][1] if runs else None,
                terminal=endings[-1].strip() if endings else '未提取到unittest结束标记',
                counts=counts, failures=[safe_text(x) for x in issues],
                causes=[safe_text(x[:600]) for x in causes[-12:]],
                skipReasons=[safe_text(x) for x in skipped],
                sha256=hashlib.sha256(raw).hexdigest(), size=len(raw))


def version_context(root):
    def git(*args):
        run = subprocess.run(['git', *args], cwd=root, capture_output=True, text=True, timeout=15)
        return run.stdout.strip() if run.returncode == 0 else '未知'
    try:
        return {'commit': git('rev-parse', 'HEAD'),
                'workingTree': '有未提交/未跟踪变更' if git('status', '--porcelain', '--untracked-files=normal') else 'clean',
                'environment': f'{platform.platform()}; Python {platform.python_version()}'}
    except (OSError, subprocess.TimeoutExpired):
        return {'commit': '未知', 'workingTree': '未知', 'environment': platform.platform()}


def atomic_markdown(path, content):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix='.report-', suffix='.tmp', dir=path.parent)
    try:
        with os.fdopen(descriptor, 'w', encoding='utf-8', newline='\n') as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        if path.read_text(encoding='utf-8') != content:
            raise OSError('Report read-back mismatch')
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def render_run(result, summaries):
    run_id = Path(result['runtime']).name
    lines = [f'<!-- run:{run_id} -->', f'## 运行 {run_id}', '',
             f"- 时间：{result.get('startedAt', '未知')} → {result.get('completedAt', '未知')}",
             f"- 原结果：{result.get('passed', '未知/未完成')}；测试遍历完成：{result.get('testsCompleted', '未知')}。该结果只覆盖下表，不代表整个产品验收通过。",
             f"- 版本：{result.get('commit', '历史结果未记录，不能用当前HEAD补填')}；工作区：{result.get('workingTree', '未知')}",
             f"- 环境：{safe_text(result.get('environment', '历史结果未记录'))}；隔离PostgreSQL：{result.get('isolatedPostgresql', '未知')}",
             f"- 资源：端口关闭={result.get('portClosed', '非PG或未知')}；剩余测试schema={safe_text(result.get('remainingTestSchemas', '未记录'))}",
             '', '| 测试模式/命令参数 | 退出码 | 执行数 | 失败/错误/跳过 | 结束标记 |', '|---|---:|---:|---|---|']
    for row in result.get('tests', []):
        summary = summaries.get(row['pattern'], {})
        count = summary.get('counts', {})
        lines.append(f"| {safe_text(row['pattern'])} | {row.get('exitCode', '未知')} | {summary.get('ran', '未知')} | {count.get('failures', '?')}/{count.get('errors', '?')}/{count.get('skipped', '?')} | {safe_text(summary.get('terminal', '日志缺失/未解析'))} |")
    lines += ['', '复现命令：在server-video-service中使用同版本环境，运行对应 `tools/accept_m111_updates.py` 或 `tools/accept_m112_lifecycle.py`，每行传 `--pattern <测试模式>`；原运行隔离PG为true时加 `--postgres`。未知版本不可视为精确复现。', '']
    for pattern, summary in summaries.items():
        for issue in summary.get('failures', []) + summary.get('causes', []) + summary.get('skipReasons', []):
            lines.append(f'- {safe_text(pattern)}：{issue}')
    if result.get('runnerError'):
        lines.append(f"- Runner异常：{safe_text(result['runnerError'])}")
    lines += ['', f"清理状态：{safe_text(result.get('cleanup', '历史材料迁移，见清单'))}", '', f'<!-- end-run:{run_id} -->', '']
    return '\n'.join(lines)


def upsert_run(report, title, result, summaries):
    report = Path(report)
    content = report.read_text(encoding='utf-8') if report.exists() else (
        f'# {title} 测试报告\n\n'
        '本报告是该后端验收脚本范围的唯一长期测试输出。各次运行按原结果保留，失败、跳过和未验证不被后续成功覆盖；不替代Android/管理后台/生产联合验收。原始日志不是永久附件。\n\n')
    run_id = Path(result['runtime']).name
    start, end = f'<!-- run:{run_id} -->', f'<!-- end-run:{run_id} -->'
    block = render_run(result, summaries)
    if start in content:
        first = content.index(start)
        last = content.index(end, first) + len(end)
        content = content[:first] + block.rstrip() + content[last:]
    else:
        content = content.rstrip() + '\n\n' + block
    atomic_markdown(report, content)


def check_owned_runtime(root, runtime, prefix):
    root, runtime = Path(root).resolve(), Path(runtime)
    staging = root / '.tmp'
    attributes = staging.lstat()
    if staging.is_symlink() or getattr(attributes, 'st_file_attributes', 0) & getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 0x400):
        raise ValueError('Refusing redirected temporary root')
    if runtime.is_symlink() or runtime.resolve().parent != (root / '.tmp').resolve():
        raise ValueError('Not a direct owned .tmp child')
    if not runtime.name.startswith(prefix) or runtime.name == prefix:
        raise ValueError('Runtime prefix mismatch')
    attributes = runtime.lstat()
    if getattr(attributes, 'st_file_attributes', 0) & getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 0x400):
        raise ValueError('Refusing redirected runtime')
    def fail_walk(error):
        raise error
    for directory, folders, files in os.walk(runtime, followlinks=False, onerror=fail_walk):
        for name in folders + files:
            item = Path(directory) / name
            attrs = item.lstat()
            if item.is_symlink() or getattr(attrs, 'st_file_attributes', 0) & getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 0x400):
                raise ValueError('Refusing runtime containing links/reparse points')
    if (runtime / 'pg-data/postmaster.pid').exists():
        raise ValueError('PostgreSQL pid file still exists')
    return runtime


def finalize_run(root, runtime, prefix, report, title, result):
    summaries = {}
    for row in result.get('tests', []):
        path = Path(row['log'])
        if path.is_file():
            summaries[row['pattern']] = summarize_log(path)
    # A process exit code of zero with no executed tests is not acceptance.
    result['passed'] = bool(result.get('passed') and summaries and
        len(summaries) == len(result.get('tests', [])) and
        all(s.get('ran') and s['terminal'].startswith('OK') and
            s['counts']['skipped'] < s['ran'] for s in summaries.values()))
    result['cleanup'] = '待清理；已持久化报告'
    upsert_run(report, title, result, summaries)
    try:
        if not result.get('resourcesStopped', False):
            raise ValueError('Runner cannot confirm resources stopped')
        owned = check_owned_runtime(root, runtime, prefix)
        shutil.rmtree(owned)
        result['cleanup'] = '完成：本次隔离临时目录已删除；不保留原始日志/结果JSON/测试数据库'
    except (OSError, ValueError) as error:
        result['cleanup'] = f'未完成：{type(error).__name__}: {safe_text(error)}'
    upsert_run(report, title, result, summaries)
    return result['cleanup'].startswith('完成：')
