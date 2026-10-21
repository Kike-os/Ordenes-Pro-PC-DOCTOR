"""Voz de ADI con OpenAI: síntesis natural (voz femenina, español latinoamericano) y transcripción de lo que dice el cliente.

- La clave de OpenAI vive solo en el servidor (la misma que usa la corrección ortográfica); el navegador recibe audio o texto, nunca la clave.
- La voz solo pronuncia respuestas de ADI ya guardadas en la conversación del cliente (o el saludo configurado): no es un servicio abierto
  de texto a voz. A la transcripción solo llega el audio de lo que el cliente dijo en la conversación.
- Tope diario de minutos (configurable): al alcanzarlo, ADI sigue por texto y con la voz del navegador. Cada uso se suma al contador del día.
- Si OpenAI falla o tarda, la interfaz usa la voz del navegador: la conversación nunca se queda muda.
"""
import base64
import json
import re
import secrets
import time
import urllib.error
import urllib.request

import adi_ai

TTS_MODEL = 'gpt-4o-mini-tts'
STT_MODEL = 'gpt-4o-mini-transcribe'
TIMEOUT = 15
MAX_AUDIO_BYTES = 1_200_000      # unos 60 s de voz comprimida; una intervención normal dura de 2 a 15 s
MAX_SPEECH_CHARS = 600           # la voz lee una versión breve; el texto completo queda en pantalla
VOICES = {'coral': 'Coral · cálida y cercana', 'nova': 'Nova · clara y juvenil', 'shimmer': 'Shimmer · suave y serena', 'sage': 'Sage · tranquila y profesional'}
STYLES = {'calido': 'cálida, cercana y amable, como una recepcionista atenta que sonríe al hablar',
          'formal': 'formal, elegante y precisa, con calma y seguridad',
          'dinamico': 'alegre, enérgica y resolutiva, sin perder la cortesía'}
SENSITIVITY = {'baja': 0.06, 'media': 0.04, 'alta': 0.025}
DEFAULTS = {'voice': 'coral', 'speed': 1.0, 'style': 'calido', 'continuous': True, 'sensitivity': 'media', 'silence_ms': 900, 'daily_minutes': 30, 'premium': True,
            'greeting': '¡Bienvenido a PC-DOCTOR S.A.! Soy ADI, tu asistente virtual. Estoy aquí para ayudarte con nuestros servicios, reparaciones, '
                        'presupuestos y citas. ¿En qué puedo ayudarte hoy?'}
SAMPLE = 'Hola, gracias por comunicarte con PC-DOCTOR S.A. Soy ADI. Con gusto te ayudo a revisar tu equipo, agendar una cita o conocer nuestros servicios.'
VOCABULARY = 'PC-DOCTOR, ADI, Órdenes Pro, Lenovo, HP, Dell, ASUS, Acer, MSI, ThinkPad, IdeaPad, Latitude, BIOS, Windows, SSD, RAM, pasta térmica, mantenimiento, presupuesto, cita'


class VoiceError(Exception):
    def __init__(self, kind, message, status=503):
        super().__init__(message)
        self.kind, self.status = kind, status


def _load(c, key, default):
    row = c.execute('SELECT value FROM system_state WHERE key=?', (key,)).fetchone()
    try:
        return json.loads(row['value']) if row else default
    except (TypeError, ValueError):
        return default


def _save(c, key, value):
    c.execute('INSERT INTO system_state(key,value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value', (key, json.dumps(value)))


def settings(c):
    saved = _load(c, 'adi_voice', {})
    out = dict(DEFAULTS)
    out.update({k: v for k, v in saved.items() if k in DEFAULTS})
    return out


def save_settings(c, data):
    """Valida y guarda la configuración. Devuelve (errores, configuración)."""
    current, errors = settings(c), {}
    clean = dict(current)
    if 'voice' in data:
        if data['voice'] in VOICES:
            clean['voice'] = data['voice']
        else:
            errors['voice'] = 'Elige una de las voces disponibles.'
    if 'style' in data:
        if data['style'] in STYLES:
            clean['style'] = data['style']
        else:
            errors['style'] = 'Estilo no válido.'
    if 'sensitivity' in data:
        if data['sensitivity'] in SENSITIVITY:
            clean['sensitivity'] = data['sensitivity']
        else:
            errors['sensitivity'] = 'Sensibilidad no válida.'
    for key, low, high, kind in (('speed', 0.8, 1.25, float), ('silence_ms', 500, 2500, int), ('daily_minutes', 0, 600, int)):
        if key in data:
            try:
                value = kind(str(data[key]).replace(',', '.'))
                if not low <= value <= high:
                    raise ValueError()
                clean[key] = round(value, 2) if kind is float else value
            except ValueError:
                errors[key] = 'Indica un valor entre %s y %s.' % (str(low).replace('.', ','), str(high).replace('.', ','))
    for key in ('continuous', 'premium'):
        if key in data:
            clean[key] = data[key] is True
    if 'greeting' in data:
        text = re.sub(r'\s+', ' ', str(data['greeting'])).strip()
        if not 10 <= len(text) <= 300:
            errors['greeting'] = 'El saludo debe tener entre 10 y 300 caracteres.'
        else:
            clean['greeting'] = text
    if not errors:
        _save(c, 'adi_voice', clean)
    return errors, clean


# ---- Consumo diario ----------------------------------------------------------------------------------------------------
def _day(now):
    return now.strftime('%Y-%m-%d')


def usage(c, now):
    return float(_load(c, 'adi_voice_usage:' + _day(now), 0) or 0)


def add_usage(c, now, seconds):
    _save(c, 'adi_voice_usage:' + _day(now), round(usage(c, now) + max(0.0, seconds), 1))


def configured():
    return bool(adi_ai.openai_key())


def available(c, now):
    """Voz de OpenAI disponible: hay clave, administración la tiene activa y no se alcanzó el tope del día."""
    cfg = settings(c)
    return configured() and cfg['premium'] and usage(c, now) < cfg['daily_minutes'] * 60


def public_config(c, now):
    cfg = settings(c)
    return {'premium': available(c, now), 'continuous': cfg['continuous'], 'speed': cfg['speed'], 'greeting': cfg['greeting'],
            'vad': {'threshold': SENSITIVITY[cfg['sensitivity']], 'silence_ms': cfg['silence_ms']}}


def admin_status(c, now):
    cfg = settings(c)
    return {'settings': cfg, 'voices': VOICES, 'styles': {k: v.split(',')[0].capitalize() for k, v in STYLES.items()}, 'sensitivities': list(SENSITIVITY),
            'configured': configured(), 'available': available(c, now), 'used_seconds': usage(c, now), 'tts_model': TTS_MODEL, 'stt_model': STT_MODEL,
            'chat_model': adi_ai.model() if adi_ai.provider() else ''}


# ---- Texto para la voz -------------------------------------------------------------------------------------------------
def _money(match):
    whole, cents = match.group(1).replace('.', ''), match.group(2)
    words = whole + (' dólares' if whole != '1' else ' dólar')
    return words + (' con ' + cents.lstrip('0') + ' centavos' if cents and cents.strip('0') else '')


def speech_text(text):
    """Versión hablada de una respuesta: sin enlaces ni listas técnicas, con el nombre de la empresa, los importes y los códigos
    pronunciables, y breve (el texto completo sigue en pantalla)."""
    lines = [line for line in str(text or '').splitlines() if line.strip() and '/citas?' not in line and not line.strip().startswith('http')]
    value = ' '.join(lines)
    value = re.sub(r'https?://\S+', 'el enlace indicado', value)
    value = re.sub(r'(?:\borden\s+)?PCD-\d{8}-0*(\d+)', r'orden \1', value, flags=re.I)
    value = re.sub(r'PC[\s\-‑–]*DOCTOR(\s*,?\s*S\.?\s?A\.?)?', lambda m: 'Pe ce dóctor' + (', ese a' if m.group(1) else ''), value, flags=re.I)
    value = re.sub(r'\bS\.\s?A\.(?![\wáéíóúñ])', 'ese a', value)
    value = re.sub(r'\$\s?(\d{1,3}(?:\.\d{3})*|\d+)(?:,(\d{2}))?', _money, value)
    value = re.sub(r'\bUSD\b', 'dólares', value)
    value = re.sub(r'\bADI\b', 'Adi', value)
    value = re.sub(r'[«»"*_#`~|]', '', value)
    value = re.sub(r'\s*[·•–—]\s*', ', ', value)
    value = re.sub(r'\s{2,}', ' ', value).strip()
    if len(value) > MAX_SPEECH_CHARS:
        cut = value[:MAX_SPEECH_CHARS]
        end = max(cut.rfind('. '), cut.rfind('? '), cut.rfind('! '))
        value = (cut[:end + 1] if end > 120 else cut.rsplit(' ', 1)[0] + '.') + ' Te dejo el detalle completo en el chat.'
    return value


def instructions(cfg):
    pace = 'un poco más pausado de lo normal' if cfg['speed'] < 0.95 else 'un poco más ágil de lo normal' if cfg['speed'] > 1.05 else 'natural'
    return ('Eres ADI, la asistente virtual de PC-DOCTOR S.A., un taller de servicio técnico de computadoras en Ecuador. '
            'Habla en español latinoamericano neutro, con voz femenina adulta y un tono ' + STYLES[cfg['style']] + '. '
            'Usa entonación humana, pausas breves entre ideas y variaciones naturales de expresión; nunca suenes como si leyeras de forma mecánica. '
            'Ritmo ' + pace + '. Pronuncia «Pe ce dóctor» como el nombre de la empresa, las marcas (Lenovo, HP, Dell, ASUS, Acer, MSI) y los términos técnicos '
            'como se dicen en Latinoamérica, y los importes con claridad.')


# ---- OpenAI ------------------------------------------------------------------------------------------------------------
def _request(url, data, headers, binary=False):
    request = urllib.request.Request(url, data=data, headers=dict({'Authorization': 'Bearer ' + adi_ai.openai_key()}, **headers), method='POST')
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            raw = response.read(4_000_000)
            return raw if binary else json.loads(raw.decode('utf-8'))
    except urllib.error.HTTPError as error:
        if error.code in (401, 403):
            raise VoiceError('credenciales', 'OpenAI rechazó la clave configurada.') from None
        if error.code == 429:
            raise VoiceError('cuota', 'OpenAI alcanzó su límite de uso. ADI usa la voz del navegador por ahora.') from None
        raise VoiceError('proveedor', 'OpenAI respondió con el código %d.' % error.code) from None
    except (urllib.error.URLError, TimeoutError, OSError):
        raise VoiceError('conexion', 'No se pudo conectar con OpenAI. ADI usa la voz del navegador por ahora.') from None
    except ValueError:
        raise VoiceError('proveedor', 'OpenAI devolvió una respuesta que no se pudo leer.') from None


_cache = {}


def synthesize(c, now, text, cfg=None, count=True):
    """Audio MP3 de `text` con la voz configurada. Devuelve (bytes, segundos estimados). Las frases repetidas (saludo, muestras) se reutilizan."""
    cfg = cfg or settings(c)
    if not configured():
        raise VoiceError('configuracion', 'La voz de OpenAI no está configurada en el servidor.')
    spoken = speech_text(text)
    if not spoken:
        raise VoiceError('vacio', 'No hay nada que leer.', 400)
    seconds = max(1.0, len(spoken) / 14.0 / max(cfg['speed'], 0.5))
    key = (cfg['voice'], cfg['style'], cfg['speed'], spoken)
    cached = _cache.get(key)
    if cached and cached[0] > time.time():
        return cached[1], seconds
    audio = _request('https://api.openai.com/v1/audio/speech',
                     json.dumps({'model': TTS_MODEL, 'voice': cfg['voice'], 'input': spoken, 'instructions': instructions(cfg), 'response_format': 'mp3'}).encode(),
                     {'Content-Type': 'application/json'}, binary=True)
    if not audio or len(audio) < 100:
        raise VoiceError('proveedor', 'OpenAI no devolvió audio.')
    if count:
        add_usage(c, now, seconds)
    if len(_cache) > 60:
        _cache.clear()
    _cache[key] = (time.time() + 6 * 3600, audio)
    return audio, seconds


def transcribe(c, now, audio, mime, duration_ms):
    """Texto de lo que dijo el cliente (español). El audio no se guarda en ningún sitio."""
    if not configured():
        raise VoiceError('configuracion', 'La transcripción de OpenAI no está configurada en el servidor.')
    if not audio or len(audio) > MAX_AUDIO_BYTES:
        raise VoiceError('tamano', 'La grabación es demasiado larga. Habla en frases más cortas.', 400)
    extension = 'mp4' if 'mp4' in mime else 'ogg' if 'ogg' in mime else 'wav' if 'wav' in mime else 'webm'
    boundary = '----adi' + secrets.token_hex(12)
    parts = []
    for name, value in (('model', STT_MODEL), ('language', 'es'), ('response_format', 'json'), ('prompt', 'Conversación con la asistente de un taller de computadoras. Vocabulario: ' + VOCABULARY + '.')):
        parts.append(('--%s\r\nContent-Disposition: form-data; name="%s"\r\n\r\n%s\r\n' % (boundary, name, value)).encode())
    parts.append(('--%s\r\nContent-Disposition: form-data; name="file"; filename="voz.%s"\r\nContent-Type: %s\r\n\r\n' % (boundary, extension, mime or 'audio/webm')).encode() + audio + b'\r\n')
    parts.append(('--%s--\r\n' % boundary).encode())
    data = _request('https://api.openai.com/v1/audio/transcriptions', b''.join(parts), {'Content-Type': 'multipart/form-data; boundary=' + boundary})
    seconds = min(60.0, max(1.0, (duration_ms or 0) / 1000.0))
    add_usage(c, now, seconds)
    return re.sub(r'\s+', ' ', str(data.get('text') or '')).strip()[:3000]


def encode(audio):
    return base64.b64encode(audio).decode()
