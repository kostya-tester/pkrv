import requests
from requests.auth import HTTPBasicAuth
import time
import logging

class JenkinsManager:
    def __init__(self, url, user, token, log_manager=None):
        self.url = url.rstrip('/')
        self.auth = HTTPBasicAuth(user, token)
        self.logger = log_manager or logging.getLogger(__name__)
        self.session = requests.Session()
        self.session.auth = self.auth

    def trigger_job(self, job_name, parameters=None):
        """Запуск Jenkins Job с параметрами."""
        try:
            if parameters:
                trigger_url = f"{self.url}/job/{job_name}/buildWithParameters"
                response = self.session.post(trigger_url, data=parameters)
            else:
                trigger_url = f"{self.url}/job/{job_name}/build"
                response = self.session.post(trigger_url)

            if response.status_code in [200, 201]:
                self.logger.info(f"Jenkins: Job '{job_name}' triggered successfully.")
                return True
            else:
                self.logger.error(f"Jenkins: Failed to trigger job. Status: {response.status_code}")
                return False
        except Exception as e:
            self.logger.error(f"Jenkins: Error triggering job: {str(e)}")
            return False

    def get_job_status(self, job_name):
        """Проверка последнего результата выполнения задачи."""
        try:
            api_url = f"{self.url}/job/{job_name}/lastBuild/api/json"
            response = self.session.get(api_url)
            if response.status_code == 200:
                data = response.json()
                return {
                    "result": data.get("result"), # SUCCESS, FAILURE, ABORTED
                    "building": data.pyget("building"),
                    "number": data.get("number")
                }
            return None
        except Exception as e:
            self.logger.error(f"Jenkins: Error getting status: {str(e)}")
            return None
