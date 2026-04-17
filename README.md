# Аудиовизуализация

Приложение для создания и проигрывания сцен с реакцией на звук: изображения, волна, осциллограф, текст, название трека (VirtualDJ), линии.

## Требования

- Windows 10/11 (основная целевая платформа)
- Python 3.10+
- Звуковая подсистема с поддержкой loopback (WASAPI) для захвата системного звука

## Установка

```bash
pip install -r requirements.txt
```

Для сборки `.exe`:

```bash
pip install -r requirements-dev.txt
```

## Запуск

```bash
python main.py
```

Подробный лог в консоль: переменная окружения `AUDIOVIZ_DEBUG=1` (уровень логирования DEBUG).

## Структура проекта

| Путь | Назначение |
|------|------------|
| [main.py](main.py) | Точка входа, логирование, загрузка QSS |
| [app/paths.py](app/paths.py) | Стартовые каталоги для файловых диалогов |
| [ui/main_window.py](ui/main_window.py) | Главное окно, режимы, геометрия окна |
| [ui/image_import_edit_dialog.py](ui/image_import_edit_dialog.py) | Импорт изображения: удаление фона по цвету / заливке |
| [ui/canvas_view.py](ui/canvas_view.py) | Вид графической сцены в режиме редактора |
| [modes/creation_mode.py](modes/creation_mode.py) | Редактор сцены |
| [modes/playback_mode.py](modes/playback_mode.py) | Проигрывание и захват аудио |
| [audio_capture.py](audio_capture.py) | Захват через `soundcard` в отдельном потоке |
| [elements/](elements/) | Элементы сцены (волна, текст, …) |
| [widgets/](widgets/) | Панель заголовка, свойств, кнопки |
| [config/app_settings.py](config/app_settings.py) | Настройки (QSettings) |
| [resources/styles_classic.qss](resources/styles_classic.qss), [resources/styles_glass.qss](resources/styles_glass.qss) | Темы интерфейса (по умолчанию classic) |

Устаревший монолитный файл `main_window.py` в корне только реэкспортирует `MainWindow` для совместимости.

## Настройки

- **⚙ в заголовке** или настройки из интерфейса: порог тишины (RMS), отладка аудио в консоль, дополнительные пути к `Tracklist.txt` VirtualDJ, **стиль интерфейса** (классический / стекло).
- Сохраняются автоматически (реестр Windows / QSettings).
- **F1** — «О программе», **F11** — полноэкранный режим.

## Захват звука (troubleshooting)

1. В проигрывании выберите **устройство вывода**, с которого реально идёт звук (динамики/наушники). Нужен loopback этого выхода.
2. Если уровень нулевой — проверьте громкость, другое устройство в списке и что звук действительно воспроизводится.
3. При «дёргании» на тишине настройте **порог тишины** в настройках (выше — агрессивнее глушит шум).

## Сборка исполняемого файла (Windows)

Рекомендуется скрипт (подтягивает PyQt6 полностью):

```powershell
.\scripts\build_windows.ps1
```

Альтернатива:

```bash
pyinstaller build_exe.spec
```

Результат: каталог `dist/AudioVisualization/` с `AudioVisualization.exe`. Первый запуск может блокироваться антивирусом; при необходимости установите [Visual C++ Redistributable](https://learn.microsoft.com/en-us/cpp/windows/latest-supported-vc-redist).

### Чеклист перед релизом

1. Обновить версию в [app/version.py](app/version.py).
2. Собрать `exe` и проверить: стартовый диалог, редактор, импорт картинки (диалог фона), открытие JSON в режиме «Проигрывание», сохранение проекта.
3. Убедиться, что в `build_exe.spec` и `scripts/build_windows.ps1` перечислены все модули с **отложенным импортом** внутри функций (сейчас явно: `ui.image_import_edit_dialog`, `app.paths`).
4. В репозитории не коммитить каталоги `dist/` и `build/` (см. [.gitignore](.gitignore)).

## Горячие клавиши

- **F11** — полноэкранный режим  
- **F1** — о программе  
- В **редакторе** (не в полях ввода): **Ctrl+Z** / **Ctrl+Y** — отмена / повтор, **Delete** — удалить выделенные элементы  

## Лицензия и версия

Версия задаётся в [app/version.py](app/version.py).
