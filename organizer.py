import os
import shutil
import hashlib
from datetime import datetime
from PIL import Image
import re
from watchdog.events import FileSystemEventHandler
import time


def sanitize_folder_name(name, max_length=150):
    """
    Очищает и сокращает имя папки
    """
    # Сначала заменяем недопустимые символы
    cleaned = re.sub(r'[<>:/\\|?*"]', '_', name)
    
    # Если имя слишком длинное, обрезаем его
    if len(cleaned) > max_length:
        # Берем первые (max_length - 5) символов и добавляем хеш
        short_hash = generate_short_hash(cleaned)
        cleaned = f"{cleaned[:max_length-5]}_{short_hash}"
    
    return cleaned

def extract_keywords(prompt, count=3):
    words = prompt.split()
    return "_".join(words[count:]) if len(words) >= count else "_".join(words)

def generate_short_hash(prompt):
    hash_object = hashlib.md5(prompt.encode("utf-8"))
    return hash_object.hexdigest()[:4]

def create_folder(folder_name):
    if not os.path.exists(folder_name):
        os.makedirs(folder_name)

def get_file_date(file_path):
    timestamp = os.path.getmtime(file_path)
    return datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d")

def create_or_update_text_file(folder_name, file_name, content):
    file_path = os.path.join(folder_name, file_name)
    with open(file_path, "w", encoding="utf-8") as file:
        file.write(content + "\n")

def is_image_file(file_path):
    valid_extensions = [".jpg", ".jpeg", ".png", ".bmp", ".gif"]
    _, extension = os.path.splitext(file_path)
    return extension.lower() in valid_extensions

def find_substring(text, start_tag, end_tag):
    lower_text = text.lower()
    lower_start = start_tag.lower()
    lower_end = end_tag.lower()

    start_idx = lower_text.find(lower_start)
    if start_idx == -1:
        return None
    start_idx += len(start_tag)

    end_idx = lower_text.find(lower_end, start_idx)
    if end_idx == -1:
        return text[start_idx:].strip()
    
    return text[start_idx:end_idx].strip()

def extract_prompt_from_metadata(image_path):
    try:
        with Image.open(image_path) as img:
            metadata = img.info
            parameters = metadata.get("parameters", "")
            if not parameters:
                return None
            
            # Инициализируем значения по умолчанию
            pos_prompt = "unknown"
            neg_prompt = "unknown"
            model = "unknown"
            
            # Очищаем параметры от "Parameters:" в начале
            if parameters.startswith("Parameters:"):
                parameters = parameters[len("Parameters:"):].strip()
            
            # Ищем границы промптов и параметров
            steps_marker = "Steps:"
            model_marker = "Model:"
            denoising_marker = "Denoising strength:"
            
            # Ищем негативный промпт
            neg_markers = ["Negative prompt:", "Negative Prompt:"]
            neg_start = -1
            used_marker = None
            
            for marker in neg_markers:
                pos = parameters.find(marker)
                if pos != -1:
                    neg_start = pos
                    used_marker = marker
                    break
            
            # Извлекаем позитивный промпт
            if neg_start != -1:
                pos_prompt = parameters[:neg_start].strip()
                # Ищем конец негативного промпта
                neg_text = parameters[neg_start + len(used_marker):]
                steps_pos = neg_text.find(steps_marker)
                if steps_pos != -1:
                    neg_prompt = neg_text[:steps_pos].strip()
                else:
                    neg_prompt = neg_text.strip()
            else:
                # Если нет негативного промпта, ищем конец позитивного
                steps_pos = parameters.find(steps_marker)
                if steps_pos != -1:
                    pos_prompt = parameters[:steps_pos].strip()
                else:
                    pos_prompt = parameters.strip()
            
            # Улучшенное извлечение модели
            model = "unknown"
            
            # Ищем основную модель
            model_patterns = [
                # Паттерн 1: Стандартный формат
                {
                    'start': "Model: ",
                    'end': ["Clip skip:", ", Clip", "ControlNet", "Style Selector", "Version:", "Denoising strength:"],
                    'exclude_if_before': ["ControlNet", "Module:"]  # Не извлекаем, если перед Model: есть эти слова
                },
                # Паттерн 2: Формат с хешем
                {
                    'start': "Model hash: ",
                    'end': ["Model:", "Denoising strength:"],
                    'exclude_if_before': ["ControlNet", "Module:"]
                }
            ]
            
            for pattern in model_patterns:
                start_marker = pattern['start']
                # Проверяем все вхождения start_marker
                start_pos = 0
                while True:
                    start_idx = parameters.find(start_marker, start_pos)
                    if start_idx == -1:
                        break
                        
                    # Проверяем, нет ли исключающих слов перед маркером
                    text_before = parameters[max(0, start_idx-50):start_idx]
                    if any(excl in text_before for excl in pattern['exclude_if_before']):
                        start_pos = start_idx + 1
                        continue
                    
                    start_idx += len(start_marker)
                    end_idx = float('inf')
                    
                    # Ищем ближайший конец
                    for end_marker in pattern['end']:
                        marker_idx = parameters.find(end_marker, start_idx)
                        if marker_idx != -1 and marker_idx < end_idx:
                            end_idx = marker_idx
                    
                    if end_idx != float('inf'):
                        model_text = parameters[start_idx:end_idx].strip()
                        if model_text:
                            model = model_text.strip().rstrip(',')
                            # Если нашли основную модель, прерываем поиск
                            break
                    
                    start_pos = start_idx
                
                if model != "unknown":
                    break
            
            # Очистка модели от лишних данных
            if ',' in model:
                # Берем первую часть, если есть запятая
                model = model.split(',')[0].strip()
            
            # Проверяем и устанавливаем значения по умолчанию для пустых полей
            if not pos_prompt or pos_prompt.isspace():
                pos_prompt = "unknown"
            if not neg_prompt or neg_prompt.isspace():
                neg_prompt = "unknown"
            if not model or model.isspace():
                model = "unknown"
            
            return (pos_prompt, neg_prompt, model)
            
    except Exception as e:
        print(f"Ошибка при извлечении метаданных из {image_path}: {e}")
        return None
    
def handle_duplicate(destination_path):
    base, extension = os.path.splitext(destination_path)
    counter = 1
    new_destination = f"{base}_{counter}{extension}"
    while os.path.exists(new_destination):
        counter += 1
        new_destination = f"{base}_{counter}{extension}"
    return new_destination

def process_file(source_path, project_folder):
    # Проверяем свободное место перед обработкой
    if not check_disk_space(project_folder):
        return {
            "status": "error", 
            "message": "Недостаточно места на диске (требуется минимум 100MB)"
        }
    
    if not os.path.isfile(source_path):
        return {"status": "not_a_file"}
    
    # Добавляем задержку и повторные попытки для занятых файлов
    max_attempts = 3
    attempt = 0
    while attempt < max_attempts:
        try:
            result = extract_prompt_from_metadata(source_path)
            break
        except PermissionError:
            attempt += 1
            if attempt == max_attempts:
                return {
                    "status": "error",
                    "message": f"Файл {source_path} занят другим процессом. Попробуйте позже."
                }
            time.sleep(1)  # Ждем секунду перед следующей попыткой
    
    if result is None:
        dest_path = os.path.join(project_folder, os.path.basename(source_path))
        if os.path.exists(dest_path):
            dest_path = handle_duplicate(dest_path)
        try:
            if safe_move_file(source_path, dest_path):
                return {"status": "moved_to_root", "destination": dest_path}
            else:
                return {
                    "status": "error", 
                    "message": f"Не удалось переместить файл {source_path} в {dest_path}"
                }
        except Exception as e:
            return {"status": "error", "message": f"Ошибка при перемещении файла {source_path} в {dest_path}: {e}"}
    
    # Извлекаем данные из результата
    if len(result) == 4:
        pos_prompt, neg_prompt, model, metadata_content = result
    else:
        pos_prompt, neg_prompt, model = result
        metadata_content = None
    
    # Создаем структуру папок
    date_folder_name = get_file_date(source_path)
    date_folder = os.path.join(project_folder, date_folder_name)
    create_folder(date_folder)

    # Используем новую функцию для создания имени папки
    folder_name = create_folder_name(pos_prompt, neg_prompt, model)
    folder_name = sanitize_folder_name(folder_name)
    prompt_folder = os.path.join(date_folder, folder_name)
    create_folder(prompt_folder)

    # Сохраняем только основные метаданные
    prompt_content = f"Positive Prompt: {pos_prompt}\nNegative Prompt: {neg_prompt}\nModel: {model}"
    create_or_update_text_file(prompt_folder, "prompt.txt", prompt_content)

    # Используем безопасное перемещение
    destination_path = os.path.join(prompt_folder, os.path.basename(source_path))
    if os.path.exists(destination_path):
        destination_path = handle_duplicate(destination_path)

    try:
        safe_move_file(source_path, destination_path)
        return {"status": "moved_to_prompt_folder", "destination": destination_path}
    except Exception as e:
        return {"status": "error", "message": f"Ошибка при перемещении файла {source_path} в {destination_path}: {e}"}
    
def process_all_files(output_folder, project_folder, log_callback=None):
    total_files = 0
    processed_files = 0

    for root, dirs, files in os.walk(output_folder):
        for file_name in files:
            file_path = os.path.join(root, file_name)
            if is_image_file(file_path):
                total_files += 1

    for root, dirs, files in os.walk(output_folder):
        for file_name in files:
            file_path = os.path.join(root, file_name)
            if is_image_file(file_path):
                result = process_file(file_path, project_folder)
                processed_files += 1
                if log_callback:
                    if result["status"] == "moved_to_root":
                        log_callback(f"Перемещён в корневую папку: {result['destination']}")
                    elif result["status"] == "moved_to_prompt_folder":
                        log_callback(f"Перемещён в папку промпта: {result['destination']}")
                    elif result["status"] == "error":
                        log_callback(result["message"])
                yield processed_files, total_files, result

class OutputFolderHandler(FileSystemEventHandler):

    def __init__(self, project_folder, log_callback):
        self.project_folder = project_folder
        self.log = log_callback

    def on_created(self, event):
        if not event.is_directory and is_image_file(event.src_path):
            self.log(f"Новый файл обнаружен: {event.src_path}")
            # Добавляем небольшую задержку, чтобы файл успел освободиться
            time.sleep(0.5)
            result = process_file(event.src_path, self.project_folder)
            if result["status"] == "moved_to_root":
                self.log(f"Перемещён в корневую папку: {result['destination']}")
            elif result["status"] == "moved_to_prompt_folder":
                self.log(f"Перемещён в папку промпта: {result['destination']}")
            elif result["status"] == "error":
                self.log(result["message"])

def check_disk_space(path, required_space_mb=100):
    """
    Проверяет, достаточно ли свободного места на диске.
    
    Args:
        path: путь к папке, где нужно проверить место
        required_space_mb: минимальное требуемое место в мегабайтах
        
    Returns:
        bool: True если места достаточно, False если нет
    """
    try:
        # Получаем информацию о свободном месте
        free_bytes = shutil.disk_usage(path).free
        free_mb = free_bytes / (1024 * 1024)  # Конвертируем байты в мегабайты
        
        return free_mb >= required_space_mb
    except Exception as e:
        print(f"Ошибка при проверке места на диске: {e}")
        return False

def safe_move_file(source, destination):
    """
    Безопасное перемещение файла с повторными попытками
    """
    max_attempts = 3
    for attempt in range(max_attempts):
        try:
            # Сначала пробуем просто переместить
            shutil.move(source, destination)
            return True
        except PermissionError:
            try:
                # Если не получается, пробуем копировать и удалить
                shutil.copy2(source, destination)
                os.remove(source)
                return True
            except Exception:
                if attempt == max_attempts - 1:
                    raise
                time.sleep(1)
    return False

def create_folder_name(pos_prompt, neg_prompt, model):
    """
    Создает читабельное имя папки на основе промптов
    """
    # Извлекаем ключевые слова из позитивного промпта
    pos_words = pos_prompt.split()
    key_words = []
    
    # Берем только значимые слова (длиннее 3 букв, без специальных символов)
    for word in pos_words:
        word = re.sub(r'[^\w\s]', '', word)
        if len(word) > 3 and word.lower() not in ['with', 'and', 'the', 'for', 'from']:
            key_words.append(word)
    
    # Берем до 3-х ключевых слов
    folder_name = '_'.join(key_words[:3])
    
    # Если нет ключевых слов, используем модель
    if not folder_name:
        folder_name = model.split('_')[0]  # Берем первую часть имени модели
    
    # Добавляем короткий хеш для уникальности
    hash_value = generate_short_hash(f"{pos_prompt}{neg_prompt}{model}")
    
    return f"{folder_name}_{hash_value}"