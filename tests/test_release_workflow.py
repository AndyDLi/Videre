"""Execute workflow commands without Git mutations or a production cluster."""

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
SOURCE = "a" * 40
RECORD = "b" * 40
NEWER = "c" * 40
IMAGES = {
    "backend": "ghcr.io/andydli/videre-backend:1.2.3-aaaaaaa",
    "simulator": "ghcr.io/andydli/videre-simulator:1.2.3-aaaaaaa",
    "frontend": "ghcr.io/andydli/videre-frontend:4.5.6-aaaaaaa",
}
MANIFESTS = {
    "backend": "k8s/backend/30-deployment.yaml",
    "simulator": "k8s/simulator/20-deployment.yaml",
    "frontend": "k8s/frontend/30-deployment.yaml",
}

# Only Git/cluster boundaries are fake. Bash, sed, grep, file writes and fail-fast
# behavior execute unchanged. Unexpected commands fail rather than invoke real Git.
COMMAND = r"""
import json, os, sys
from pathlib import Path
args = sys.argv[1:]
command = Path(sys.argv[0]).name
with open('calls.jsonl', 'a') as log:
    log.write(json.dumps([command, *args]) + '\n')
if command == 'git':
    if args[0] == 'ls-remote':
        counter = Path('probes')
        n = int(counter.read_text()) if counter.exists() else 0
        refs = json.loads(os.environ['REMOTE_REFS'])
        ref = refs[min(n, len(refs) - 1)]
        counter.write_text(str(n + 1))
        if ref == 'error': sys.exit(128)
        if ref: print(ref + '\trefs/heads/main')
    elif args == ['rev-parse', 'HEAD']:
        print(os.environ['RECORD_SHA'] if Path('committed').exists() else os.environ['GITHUB_SHA'])
    elif args == ['diff', '--quiet']:
        if os.environ.get('FAIL_DIFF'): sys.exit(128)
        sys.exit(0 if os.environ.get('NO_CHANGE') else 1)
    elif args[0] in ('config', 'add'):
        pass
    elif args[0] == 'commit':
        Path('committed').touch()
    elif args == ['push', 'origin', 'HEAD:main']:
        if os.environ.get('FAIL_PUSH'): sys.exit(1)
    else:
        sys.exit('unexpected git command: ' + str(args))
else:
    if args[:2] == ['set', 'image']:
        name = args[2].split('/')[1]
        assignment = args[3].split('=', 1)
        assert assignment[0] == name
        state = json.loads(Path('images.json').read_text()) if Path('images.json').exists() else {}
        state[name] = assignment[1]
        Path('images.json').write_text(json.dumps(state))
    elif args[:2] == ['rollout', 'status']:
        name = args[2].split('/')[1]
        if os.environ.get('FAIL_ROLLOUT') == name: sys.exit(1)
    elif args[:2] == ['get', 'deployment']:
        name = args[2]
        state = json.loads(Path('images.json').read_text())
        print('unexpected:old' if os.environ.get('WRONG_IMAGE') == name else state[name])
    else:
        sys.exit('unexpected kubectl command: ' + str(args))
"""


def workflow():
    return yaml.safe_load((ROOT / '.github/workflows/ci.yml').read_text())


def script_for(job, prefix):
    blocks = [s['run'] for s in workflow()['jobs'][job]['steps'] if s.get('name', '').startswith(prefix)]
    assert blocks, (job, prefix)
    expressions = {
        'steps.versions.outputs.python_version': '1.2.3',
        'steps.versions.outputs.frontend_version': '4.5.6',
        'steps.versions.outputs.short_sha': 'aaaaaaa',
        'env.IMAGE_PREFIX': 'ghcr.io/andydli/videre',
        'env.PYTHON_TAG': '1.2.3-aaaaaaa',
        'env.FRONTEND_TAG': '4.5.6-aaaaaaa',
        'needs.build-and-push.outputs.record_sha': RECORD,
    }
    return re.sub(r'\$\{\{\s*(.*?)\s*\}\}', lambda match: expressions[match[1]], '\n'.join(blocks))


def run_workflow(tmp_path, job, refs, **options):
    bin_dir = tmp_path / 'bin'
    bin_dir.mkdir()
    for name in ('git', 'kubectl'):
        executable = bin_dir / name
        executable.write_text(f'#!{sys.executable}\n' + COMMAND)
        executable.chmod(0o755)
    for name, relative in MANIFESTS.items():
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        image = IMAGES[name] if options.get('NO_CHANGE') else f'ghcr.io/andydli/videre-{name}:old'
        path.write_text(f'          image: {image}\n')
    output, summary = tmp_path / 'output', tmp_path / 'summary'
    env = dict(os.environ, PATH=f'{bin_dir}:{os.environ["PATH"]}', REMOTE_REFS=json.dumps(refs),
               GITHUB_SHA=SOURCE, RECORD_SHA=RECORD, IMAGE_PREFIX='ghcr.io/andydli/videre',
               PYTHON_TAG='1.2.3-aaaaaaa', FRONTEND_TAG='4.5.6-aaaaaaa',
               GITHUB_OUTPUT=str(output), GITHUB_STEP_SUMMARY=str(summary),
               GITHUB_SERVER_URL='https://github.com', GITHUB_REPOSITORY='AndyDLi/Videre', GITHUB_RUN_ID='123',
               **options)
    prefix = 'Record the ' if job == 'build-and-push' else 'Deploy '
    result = subprocess.run(['bash', '-c', script_for(job, prefix)], cwd=tmp_path, env=env,
                            capture_output=True, text=True, timeout=15)
    log = tmp_path / 'calls.jsonl'
    calls = [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []
    return result, calls, output.read_text() if output.exists() else '', summary.read_text() if summary.exists() else ''


@pytest.mark.parametrize('remote', [NEWER, '', 'error'])
def test_stale_record_does_not_modify_manifests_or_git(tmp_path, remote):
    result, calls, output, _ = run_workflow(tmp_path, 'build-and-push', [remote])
    assert result.returncode != 0
    assert all(call[1] not in ('config', 'add', 'commit', 'push', 'pull') for call in calls)
    assert not output
    for name, path in MANIFESTS.items():
        assert (tmp_path / path).read_text() == f'          image: ghcr.io/andydli/videre-{name}:old\n'


def test_current_record_returns_its_full_pushed_sha(tmp_path):
    result, calls, output, _ = run_workflow(tmp_path, 'build-and-push', [SOURCE])
    assert result.returncode == 0, result.stderr
    assert ['git', 'push', 'origin', 'HEAD:main'] in calls
    assert not any(call[1] == 'pull' for call in calls)
    assert output == f'record_sha={RECORD}\n'
    for name, path in MANIFESTS.items():
        assert (tmp_path / path).read_text() == f'          image: {IMAGES[name]}\n'


def test_no_change_returns_source_sha_without_git_write(tmp_path):
    result, calls, output, _ = run_workflow(tmp_path, 'build-and-push', [SOURCE], NO_CHANGE='1')
    assert result.returncode == 0, result.stderr
    assert not any(call[1] in ('commit', 'push') for call in calls)
    assert output == f'record_sha={SOURCE}\n'


def test_failed_diff_aborts_without_committing_or_publishing_record(tmp_path):
    result, calls, output, _ = run_workflow(tmp_path, 'build-and-push', [SOURCE], FAIL_DIFF='1')
    assert result.returncode != 0
    assert not any(call[1] in ('commit', 'push') for call in calls)
    assert not output


def test_push_race_fails_without_rebase_or_record_output(tmp_path):
    result, calls, output, _ = run_workflow(tmp_path, 'build-and-push', [SOURCE], FAIL_PUSH='1')
    assert result.returncode != 0
    assert not any(call[1] == 'pull' or '--force' in call for call in calls)
    assert not output


def mutations(calls):
    return [call[3].split('/')[1] for call in calls if call[:3] == ['kubectl', 'set', 'image']]


def test_own_record_allows_ordered_rollout_and_verified_summary(tmp_path):
    result, calls, _, summary = run_workflow(tmp_path, 'deploy', [RECORD])
    assert result.returncode == 0, result.stderr
    assert mutations(calls) == ['backend', 'simulator', 'frontend']
    assert SOURCE in summary and RECORD in summary
    assert all(image in summary for image in IMAGES.values())
    assert 'https://github.com/AndyDLi/Videre/actions/runs/123' in summary


@pytest.mark.parametrize('remote', [SOURCE, NEWER, '', 'error'])
def test_deploy_rejects_source_or_superseded_record_before_mutation(tmp_path, remote):
    result, calls, _, summary = run_workflow(tmp_path, 'deploy', [remote])
    assert result.returncode != 0
    assert not mutations(calls)
    assert not summary


@pytest.mark.parametrize('stop_at', [0, 1, 2])
def test_remote_advance_stops_each_subsequent_mutation(tmp_path, stop_at):
    result, calls, _, summary = run_workflow(tmp_path, 'deploy', [RECORD] * stop_at + [NEWER])
    assert result.returncode != 0
    assert mutations(calls) == ['backend', 'simulator', 'frontend'][:stop_at]
    assert not summary


@pytest.mark.parametrize('component', ['backend', 'simulator', 'frontend'])
@pytest.mark.parametrize('failure', ['FAIL_ROLLOUT', 'WRONG_IMAGE'])
def test_failed_or_unexpected_rollout_never_records_success(tmp_path, component, failure):
    result, calls, _, summary = run_workflow(tmp_path, 'deploy', [RECORD], **{failure: component})
    assert result.returncode != 0
    order = ['backend', 'simulator', 'frontend']
    assert mutations(calls) == order[:order.index(component) + 1]
    assert not summary


def test_release_lock_spans_jobs_without_cancelling_active_rollout():
    config = workflow()
    assert config['concurrency'] == {'group': 'videre-release-${{ github.ref }}', 'cancel-in-progress': False}
    for name in ('build-and-push', 'deploy'):
        assert config['jobs'][name]['if'] == "github.event_name == 'push' && github.ref == 'refs/heads/main'"
    assert config['jobs']['test-python']['runs-on'] == 'ubuntu-latest'
    assert config['jobs']['deploy']['runs-on'] == ['self-hosted', 'videre-deploy']
