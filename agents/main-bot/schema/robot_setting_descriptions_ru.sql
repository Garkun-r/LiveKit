-- Russian descriptions for robot settings shown in Directus/admin UI.
--
-- Safe migration properties:
-- - updates only public.robot_setting_fields.description;
-- - does not change setting keys, defaults, profile values, secrets, or runtime logic;
-- - intentionally fails if the current settings manifest is incomplete.

begin;

create temp table robot_setting_descriptions_ru (
    setting_key text primary key,
    description text not null
) on commit drop;

insert into robot_setting_descriptions_ru (setting_key, description)
values
        ('fallback.use_livekit_adapter', $desc$Включает встроенный LiveKit fallback для LLM: при ошибке основной модели агент может использовать заранее указанный резервный профиль вместо ручного обходного пути.$desc$),
        ('fallback.fast_backup_provider', $desc$Провайдер резервной быстрой LLM-ветки, которая используется для коротких и срочных ответов при отказе основной быстрой модели.$desc$),
        ('fallback.fast_backup_model', $desc$Имя модели у резервного провайдера для быстрой LLM-ветки. Должно соответствовать формату выбранного провайдера.$desc$),
        ('fallback.complex_backup_provider', $desc$Провайдер резервной сложной LLM-ветки, которая используется для более тяжелых рассуждений при отказе основной сложной модели.$desc$),
        ('fallback.complex_backup_model', $desc$Имя модели у резервного провайдера для сложной LLM-ветки. Должно соответствовать формату выбранного провайдера.$desc$),

        ('llm.provider', $desc$Основной провайдер языковой модели, через которого робот генерирует ответы и принимает решения в диалоге.$desc$),
        ('llm.model', $desc$Идентификатор основной LLM-модели у выбранного провайдера. Неверное имя модели приведет к ошибке запроса к провайдеру.$desc$),
        ('llm.fallback_model', $desc$Резервная модель того же LLM-провайдера, которую можно использовать, если основная модель недоступна или не подходит для части задач.$desc$),
        ('llm.temperature', $desc$Температура генерации LLM: чем выше значение, тем более вариативными могут быть ответы; чем ниже, тем они стабильнее и предсказуемее.$desc$),
        ('llm.enable_tools', $desc$Разрешает этой LLM-модели вызывать подключенные инструменты и функции. Отключайте, если модель должна только отвечать текстом.$desc$),
        ('llm.global_tools_enabled', $desc$Общий переключатель инструментов для LLM на уровне робота. Если он выключен, инструменты не должны использоваться даже при включении в отдельных профилях.$desc$),
        ('llm.base_url', $desc$Базовый URL API провайдера LLM. Используется для прокси, региональных endpoint-ов или OpenAI-совместимых API.$desc$),
        ('llm.max_output_tokens', $desc$Максимальное количество токенов, которое LLM может сгенерировать в одном ответе. Меньшее значение ограничивает длину и стоимость ответа.$desc$),
        ('llm.top_p', $desc$Порог nucleus sampling для LLM: модель выбирает продолжение из наиболее вероятных токенов, суммарная вероятность которых не выше этого значения.$desc$),
        ('llm.thinking_level', $desc$Уровень внутреннего рассуждения для моделей Gemini, которые поддерживают thinking. Более высокий уровень может улучшить сложные ответы, но увеличивает задержку.$desc$),

        ('stt.provider', $desc$Провайдер распознавания речи, который превращает аудио пользователя в текст для дальнейшей обработки агентом.$desc$),
        ('stt.model', $desc$Идентификатор модели распознавания речи у выбранного STT-провайдера. Влияет на качество, задержку и поддержку языков.$desc$),
        ('stt.language', $desc$Язык распознавания речи в формате провайдера, например ru или ru-RU. Неверный язык ухудшает качество транскрибации.$desc$),
        ('stt.endpointing_ms', $desc$Пауза тишины в миллисекундах, после которой STT-провайдер считает фразу завершенной. Меньше значение быстрее отвечает, больше значение лучше переживает паузы внутри фразы.$desc$),
        ('stt.location', $desc$Регион или локация облачного STT-сервиса. Используется провайдерами, где endpoint или доступность модели зависят от региона.$desc$),
        ('stt.max_pause_between_words_hint_ms', $desc$Подсказка для Yandex SpeechKit: максимальная пауза между словами в миллисекундах, которая еще считается частью одной фразы.$desc$),
        ('stt.early_interim_final_enabled', $desc$Включает внутренний механизм, который может превратить последний interim-текст STT в финальный, если провайдер задерживает финализацию после конца речи.$desc$),
        ('stt.early_interim_final_delay_sec', $desc$Сколько секунд ждать финальный результат STT после конца речи перед использованием последнего стабильного interim-текста как финального.$desc$),

        ('tts.provider', $desc$Провайдер синтеза речи, который озвучивает ответы робота.$desc$),
        ('tts.model', $desc$Идентификатор модели синтеза речи у выбранного TTS-провайдера. Влияет на качество, выразительность, задержку и доступные голоса.$desc$),
        ('tts.voice_id', $desc$Идентификатор голоса у TTS-провайдера. Это не секретный ключ, а выбранный голос или voice id для синтеза.$desc$),
        ('tts.apply_text_normalization', $desc$Режим нормализации текста перед синтезом, например преобразование чисел и дат в произносимую форму. Может влиять на задержку и произношение.$desc$),
        ('tts.enable_logging', $desc$Разрешает логирование запроса на стороне TTS-провайдера, если провайдер это поддерживает. Отключение может включать режим без сохранения истории, но зависит от тарифа.$desc$),
        ('tts.language', $desc$Язык или локаль синтеза речи. Помогает провайдеру выбрать правильное произношение и правила нормализации текста.$desc$),
        ('tts.voice_name', $desc$Имя голоса у провайдера, если провайдер использует название голоса вместо отдельного voice id.$desc$),
        ('tts.voice_speed', $desc$Скорость голоса для провайдеров, где она задается отдельно от общего speed/rate. Значение 1 обычно означает стандартную скорость.$desc$),
        ('tts.voice_style', $desc$Степень усиления стиля или эмоциональной манеры голоса, если провайдер поддерживает такой параметр. Высокие значения могут увеличить выразительность и нестабильность.$desc$),
        ('tts.voice_use_speaker_boost', $desc$Усиливает сходство с исходным голосом, если провайдер поддерживает speaker boost. Может немного увеличить задержку синтеза.$desc$),
        ('tts.use_stream_input', $desc$Использует потоковую отправку текста в TTS через WebSocket или аналогичный stream-input режим. Обычно снижает задержку первого аудио.$desc$),
        ('tts.use_streaming', $desc$Включает потоковый режим синтеза, чтобы робот мог начать воспроизведение до завершения генерации всего аудио.$desc$),
        ('tts.fallback_model', $desc$Резервная TTS-модель у того же провайдера, которую можно использовать при недоступности или неподходящем поведении основной модели.$desc$),
        ('tts.speed', $desc$Общая скорость произношения для TTS-провайдера. Значение 1 обычно означает нормальную скорость; выше быстрее, ниже медленнее.$desc$),
        ('tts.speaking_rate', $desc$Скорость речи в формате Google Cloud TTS и совместимых провайдеров. Значение 1.0 обычно означает естественную скорость выбранного голоса.$desc$),
        ('tts.pitch', $desc$Высота голоса или тон синтеза. Диапазон и смысл зависят от провайдера: у одних это полутона, у других множитель или условная шкала.$desc$),
        ('tts.format', $desc$Формат аудио, который должен вернуть TTS-провайдер, например mp3, pcm, wav или opus.$desc$),
        ('tts.bitrate', $desc$Битрейт выходного аудио, если провайдер позволяет его задавать. Влияет на размер потока и качество сжатого аудио.$desc$),
        ('tts.channel', $desc$Количество аудиоканалов в результате синтеза: обычно 1 для телефонии и голосовых роботов, 2 для стерео-сценариев.$desc$),
        ('tts.intensity', $desc$Параметр выразительности или интенсивности голоса для провайдеров, которые поддерживают модификацию тембра и подачи.$desc$),
        ('tts.timbre', $desc$Параметр тембра голоса для провайдеров, которые позволяют менять окраску звучания без выбора другого voice id.$desc$),
        ('tts.sound_effects', $desc$Идентификатор или список звуковых эффектов, применяемых TTS-провайдером к синтезированной речи, если такая функция поддерживается.$desc$),
        ('tts.profile', $desc$Внутренний пресет профиля TTS в проекте. Используется для быстрого выбора набора модели, региона, формата и параметров качества.$desc$),
        ('tts.output_format', $desc$Формат выходного аудио в синтаксисе конкретного провайдера, например codec_sample-rate_bitrate у ElevenLabs.$desc$),
        ('tts.transport', $desc$Транспорт TTS-запросов: HTTP для обычных запросов или WebSocket для потокового синтеза с меньшей задержкой.$desc$),
        ('tts.region', $desc$Регион TTS-провайдера или облачной платформы. Влияет на доступность модели, маршрут запроса и задержку.$desc$),
        ('tts.ws_url', $desc$WebSocket endpoint TTS-провайдера для потокового синтеза. Не является секретом, но должен соответствовать выбранному региону и провайдеру.$desc$),
        ('tts.voice_mode', $desc$Режим выбора голоса у провайдера: готовый голос, клонированный голос или дизайнерский голос, если такие режимы поддерживаются.$desc$),
        ('tts.clone_voice_id', $desc$Идентификатор клонированного голоса, который используется, когда voice mode выбран как clone.$desc$),
        ('tts.design_voice_id', $desc$Идентификатор дизайнерского или созданного голосового профиля, который используется, когда voice mode выбран как design.$desc$),
        ('tts.rate', $desc$Скорость речи для провайдеров, где параметр называется rate. Обычно 1.0 означает стандартную скорость, выше быстрее, ниже медленнее.$desc$),
        ('tts.volume', $desc$Громкость синтезированной речи в шкале провайдера. Не заменяет нормализацию аудио в телефонии, но влияет на уровень результата TTS.$desc$),
        ('tts.connection_reuse', $desc$Разрешает переиспользовать потоковое соединение с TTS-провайдером между фрагментами, чтобы уменьшить накладные расходы и задержку.$desc$),
        ('tts.playback_on_first_chunk', $desc$Разрешает начинать воспроизведение сразу после первого полученного аудиофрагмента, не дожидаясь полного ответа TTS.$desc$),
        ('tts.api_key_env_name', $desc$Имя env-переменной, где лежит API-ключ TTS-провайдера. Здесь хранится только имя переменной, не сам секрет.$desc$),
        ('tts.min_sentence_len', $desc$Минимальная длина текстового фрагмента перед отправкой в потоковый TTS. Меньше значение ускоряет старт, но может ухудшить интонацию.$desc$),
        ('tts.voice', $desc$Имя или идентификатор голоса у провайдера, если интеграция использует поле voice вместо voice_id или voice_name.$desc$),
        ('tts.paint_pitch', $desc$Параметр Sber SaluteSpeech для SSML-тега paint: управляет акцентом по высоте тона в выделенном фрагменте речи.$desc$),
        ('tts.paint_speed', $desc$Параметр Sber SaluteSpeech для SSML-тега paint: управляет акцентом по скорости произношения в выделенном фрагменте речи.$desc$),
        ('tts.paint_loudness', $desc$Параметр Sber SaluteSpeech для SSML-тега paint: управляет акцентом по громкости в выделенном фрагменте речи.$desc$),
        ('tts.stream_context_len', $desc$Сколько предыдущих фраз передавать TTS-провайдеру как контекст для более плавной интонации при склейке потоковых фрагментов.$desc$),
        ('tts.voice_stability', $desc$Стабильность голоса ElevenLabs: выше значение дает более одинаковое звучание между генерациями, ниже может добавить эмоциональный разброс.$desc$),
        ('tts.voice_similarity_boost', $desc$Степень сходства ElevenLabs с исходным голосом. Более высокое значение сильнее удерживает voice id, но может влиять на естественность.$desc$),
        ('tts.base_url', $desc$Базовый URL API TTS-провайдера. Используется для региональных endpoint-ов, прокси или альтернативных совместимых API.$desc$),
        ('tts.language_boost', $desc$Подсказка TTS-провайдеру о языке текста, например Russian. Помогает улучшить произношение и выбор языковых правил.$desc$),
        ('tts.sample_rate', $desc$Частота дискретизации выходного аудио в герцах. Для телефонии и LiveKit важно выбирать значение, совместимое с пайплайном и форматом.$desc$),
        ('tts.prompt', $desc$Стилевой prompt для TTS-моделей, которые принимают инструкцию к манере речи: акцент, тон, темп, естественность и другие голосовые требования.$desc$),
        ('tts.location', $desc$Локация или регион облачного TTS-сервиса. Используется провайдерами, где модель или endpoint выбираются по региону.$desc$),

        ('turn.detection_mode', $desc$Способ определения конца реплики пользователя: VAD по тишине, STT endpointing, multilingual end-of-turn модель или ручной режим, если он поддержан кодом.$desc$),
        ('turn.endpointing_mode', $desc$Режим задержки после конца речи: fixed использует постоянный интервал, dynamic подстраивает задержку в пределах min/max по статистике пауз.$desc$),
        ('turn.min_endpointing_delay', $desc$Минимальная задержка в секундах после предполагаемого конца речи перед ответом робота. Меньше значение ускоряет реакцию, но повышает риск перебить пользователя.$desc$),
        ('turn.max_endpointing_delay', $desc$Максимальная задержка в секундах, до которой робот может ждать перед ответом, если endpointing считает, что пользователь мог продолжить мысль.$desc$),
        ('turn.preemptive_generation', $desc$Разрешает LiveKit начинать генерацию ответа до окончательной фиксации пользовательской реплики. Это снижает задержку, но может давать ошибки при неверном определении конца речи.$desc$),
        ('turn.early_interim_final_enabled', $desc$Включает проектный механизм ранней финализации: при VAD-режиме робот может принять последний стабильный interim STT как финальный текст после конца речи.$desc$),
        ('turn.early_interim_final_delay_sec', $desc$Задержка в секундах перед ранней финализацией interim STT после END_OF_SPEECH. Больше значение дает шанс дождаться настоящего final от провайдера.$desc$);

update public.robot_setting_fields as target
set description = source.description,
    updated_at = now()
from robot_setting_descriptions_ru as source
where target.setting_key = source.setting_key;

do $$
declare
    expected_count integer;
    updated_count integer;
    missing_keys text;
    blank_keys text;
begin
    select count(*) into expected_count
    from robot_setting_descriptions_ru;

    select count(*) into updated_count
    from public.robot_setting_fields as target
    join robot_setting_descriptions_ru as source using (setting_key)
    where target.description = source.description;

    select string_agg(source.setting_key, ', ' order by source.setting_key) into missing_keys
    from robot_setting_descriptions_ru as source
    left join public.robot_setting_fields as target using (setting_key)
    where target.setting_key is null;

    select string_agg(setting_key, ', ' order by setting_key) into blank_keys
    from public.robot_setting_fields
    where coalesce(nullif(trim(description), ''), '') = '';

    if expected_count <> 78 then
        raise exception 'Expected 78 description rows in migration, got %', expected_count;
    end if;

    if missing_keys is not null then
        raise exception 'Missing setting definitions: %', missing_keys;
    end if;

    if blank_keys is not null then
        raise exception 'Blank setting descriptions: %', blank_keys;
    end if;

    if updated_count <> expected_count then
        raise exception 'Expected to update % setting descriptions, updated %', expected_count, updated_count;
    end if;

    raise notice 'Updated % robot setting descriptions', updated_count;
end $$;

commit;
