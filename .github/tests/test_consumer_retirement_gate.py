"""A consumer retirement is major even when the signed implementation parent is unchanged."""
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
import yaml


ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('retirement_adopter_gate', ROOT / '.github/scripts/adopter_gate.py')
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)


class ConsumerRetirementGate(unittest.TestCase):
    def test_official_baseline_reads_receive_the_existing_workflow_credential(self):
        readers = {'shift-left.yml': ['adopter gate --', "recompose ludlow's party"],
                   'cut-release.yml': ['ticket 18 -- re-render'],
                   'propose-tier.yml': ["re-compose at today's date"],
                   'renovate-run.yml': ['run self-hosted renovate']}
        for workflow, names in readers.items():
            document = yaml.safe_load((ROOT / '.github/workflows' / workflow).read_text())
            steps = [step for job in document['jobs'].values() for step in job['steps']]
            for name in names:
                with self.subTest(workflow=workflow, reader=name):
                    step = next(step for step in steps if step.get('name', '').startswith(name))
                    self.assertEqual(step.get('env', {}).get('GH_TOKEN'), '${{ github.token }}',
                                     'hosted gh has no ambient login for official baseline GETs')

    def test_unchanged_parent_does_not_hide_a_composed_retirement(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            adopter, platform = root / 'adopter', root / 'platform'
            def git(repository, *args):
                return subprocess.check_output(['git', '-c', 'commit.gpgsign=false', '-c', 'tag.gpgsign=false',
                    '-c', 'core.hooksPath=/dev/null', '-C', str(repository), *args],
                    stderr=subprocess.DEVNULL, text=True, timeout=10).strip()
            for repository in (adopter, platform):
                repository.mkdir()
                git(repository, 'init', '-q')
                git(repository, 'config', 'user.name', 'synthetic test')
                git(repository, 'config', 'user.email', 'fixture@example.invalid')
            (platform / 'fixture').write_text('no real release or price\n')
            git(platform, 'add', '.')
            git(platform, 'commit', '-qm', 'synthetic parent')
            parent = git(platform, 'rev-parse', 'HEAD')
            git(platform, 'tag', 'v5.0.0')
            (adopter / 'gitops/platform').mkdir(parents=True)
            (adopter / 'gitops/platform/platform-pin.yaml').write_text(
                f'kind: GitRepository\nmetadata: {{name: platform}}\nspec:\n  ref:\n    tag: v5.0.0\n    commit: {parent}\n')
            (adopter / 'composed').mkdir()
            evidence = adopter / 'composed/evidence.json'
            evidence.write_text(json.dumps({'members': [{'version': v} for v in ('5.0.0', '6.0.0', '7.0.0')]}))
            git(adopter, 'add', '.')
            git(adopter, 'commit', '-qm', 'synthetic before')
            before = git(adopter, 'rev-parse', 'HEAD')
            evidence.write_text(json.dumps({'members': [{'version': '7.0.0'}]}))
            git(adopter, 'add', '.')
            git(adopter, 'commit', '-qm', 'synthetic retirement without authorization')
            after = git(adopter, 'rev-parse', 'HEAD')
            code, comment = gate.run(adopter, platform, before, after, 'unused', 'unused',
                                     composed_base_ref=before, composed_head_ref=after)
            self.assertEqual(code, 1, 'unreviewed retirement escaped the major refusal')
            self.assertIn('**major**', comment)
            self.assertIn('5.0.0', comment)
            self.assertIn('6.0.0', comment)


if __name__ == '__main__':
    unittest.main()
