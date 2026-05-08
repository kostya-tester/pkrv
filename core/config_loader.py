import yaml
import os

class ConfigLoader:
    def __init__(self, config_path='config.yaml'):
        self.path = config_path
        self.config = self._load()

    def _load(self):
        if not os.path.exists(self.path):
            raise FileNotFoundError(f"Config file {self.path} not found.")
        with open(self.path, 'r') as f:
            return yaml.safe_load(f)

    def get_jenkins_config(self):
        return self.config.get('jenkins', {})

    def get_benches(self):
        return self.config.get('benches', [])
