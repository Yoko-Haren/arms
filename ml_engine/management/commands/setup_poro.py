"""Build (or rebuild) Poro's local model in Ollama: the base model with Poro's persona (ml_engine/poro/Modelfile)."""
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = ("Build Poro's model in Ollama from ml_engine/poro/Modelfile on top of PORO_AI_BASE_MODEL "
            "(pull the base first, for example: ollama pull qwen2.5:3b).")

    def handle(self, *args, **options):
        conf = settings.PORO_AI
        exe = shutil.which('ollama') or os.path.join(os.environ.get('LOCALAPPDATA', ''), 'Programs', 'Ollama', 'ollama.exe')
        if not os.path.exists(exe):
            raise CommandError('Ollama is not installed (https://ollama.com). Poro still works with the computed wording.')
        source = Path(settings.BASE_DIR) / 'ml_engine' / 'poro' / 'Modelfile'
        lines = source.read_text(encoding='utf-8').splitlines()
        # the base model comes from the settings, so a stronger computer can use a larger one
        text = '\n'.join(f'FROM {conf["BASE_MODEL"]}' if line.startswith('FROM ') else line for line in lines) + '\n'
        with tempfile.TemporaryDirectory() as folder:
            modelfile = Path(folder) / 'Modelfile'
            modelfile.write_text(text, encoding='utf-8')
            self.stdout.write(f'Building "{conf["MODEL"]}" from {conf["BASE_MODEL"]} with Poro\'s persona...')
            done = subprocess.run([exe, 'create', conf['MODEL'], '-f', str(modelfile)], capture_output=True, text=True,
                                  encoding='utf-8', errors='replace')
        if done.returncode != 0:
            raise CommandError((done.stderr or done.stdout).strip()[-500:] or 'ollama create failed.')
        self.stdout.write(self.style.SUCCESS(f'"{conf["MODEL"]}" is ready. Poro rewords the School Head\'s recommendations with it.'))
