import requests
import json
import os
from packaging import version

class UpdateChecker:
    def __init__(self, current_version):
        self.current_version = current_version
        self.update_url = "https://api.github.com/repos/ваш_username/SD_Organizer/releases/latest"
        self.download_base_url = "https://github.com/ваш_username/SD_Organizer/releases/download/"

    def check_for_updates(self):
        try:
            response = requests.get(self.update_url)
            if response.status_code == 200:
                latest = response.json()
                latest_version = latest['tag_name'].lstrip('v')
                
                if version.parse(latest_version) > version.parse(self.current_version):
                    return {
                        'available': True,
                        'version': latest_version,
                        'download_url': latest['assets'][0]['browser_download_url'],
                        'changes': latest['body']
                    }
            return {'available': False}
        except Exception:
            return {'available': False}

    def download_update(self, download_url, callback=None):
        try:
            response = requests.get(download_url, stream=True)
            total_size = int(response.headers.get('content-length', 0))
            
            # Сохраняем во временную папку
            temp_path = os.path.join(os.getenv('TEMP'), 'SD_Organizer_update.exe')
            
            with open(temp_path, 'wb') as f:
                downloaded = 0
                for data in response.iter_content(chunk_size=4096):
                    downloaded += len(data)
                    f.write(data)
                    if callback:
                        callback(downloaded / total_size * 100)
            
            return temp_path
        except Exception as e:
            print(f"Ошибка загрузки обновления: {e}")
            return None 