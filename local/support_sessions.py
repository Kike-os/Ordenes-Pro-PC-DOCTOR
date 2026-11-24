"""ADI Live Support Center 4.0 · Smart Session Timeout (docs/LIVE-SUPPORT.md).

El SERVIDOR es la fuente de verdad: cada conversación tiene una sesión con su última actividad válida y su fecha de expiración
(expires_at = última actividad válida + tiempo máximo, 480 s por defecto). El cierre se aplica con una operación atómica (compare-and-set
sobre `version`) en cuanto cualquier evento toca el sistema —mensaje del cliente, consulta del chat web, webhook de WhatsApp, panel del
personal o tareas programadas— y queda registrado con la hora EXACTA de expiración (effective_close_at), aunque nadie tuviera el sistema
abierto. El contador visual solo muestra expires_at; nunca decide.

Actividad válida (reinicia el contador): mensaje del cliente, respuesta de ADI y respuesta del asesor. NO la reinician: consultas
periódicas, confirmaciones de lectura o entrega, escritura, avisos internos, el propio aviso de cierre, reintentos ni eventos duplicados.

Protecciones: no se cierra mientras ADI procesa (con límite), durante una pausa administrativa justificada (con límite) ni cuando el último
mensaje válido es del CLIENTE (la inactividad sería de PC-DOCTOR): en ese caso la conversación queda «esperando respuesta» y se alerta al
personal. Una solicitud de asesor pendiente nunca se pierde: el caso (adi_handoffs) sigue pendiente aunque la sesión se cierre.

Cierre y aviso: mensajes configurables por canal; por defecto el aviso y el mensaje de cierre se muestran en el chat web y NO se envían por
WhatsApp (respeta ventanas y plantillas de Meta: el cierre interno no es el vencimiento de la ventana de WhatsApp). Cada aviso y cierre
tiene clave de idempotencia: nunca se duplica. Activación: primero una simulación de qué se cerraría; al activar, las conversaciones
antiguas se cierran en silencio (sin avisos masivos)."""
import json
from datetime import datetime, timedelta

KEY = 'live_support_settings'
DEFAULTS = {'enabled': False, 'idle_seconds': 480, 'visual_warning_seconds': 300, 'client_warning_seconds': 420, 'processing_limit_seconds': 90,
            'max_pause_minutes': 60, 'reopen_auto': True,
            'channels': {'web': {'warning': True, 'close_message': True}, 'whatsapp': {'warning': False, 'close_message': False}},
            'warning_text': ('Estimado cliente, seguimos a su disposición. Debido a la inactividad, nuestra sesión de atención está próxima a finalizar. '
                             'Si necesita continuar, simplemente envíenos un mensaje.'),
            'close_text': ('Hemos finalizado esta sesión de atención por inactividad. Gracias por comunicarse con PC-DOCTOR. '
                           'Si necesita asistencia adicional, puede escribirnos nuevamente.')}
SWEEP_KEY, SWEEP_GAP = 'live_support_sweep', 15          # segundos mínimos entre barridos completos
NOT_INSTALLED = 'El cierre automático necesita la migración 123 (Sistema → Migraciones).'
REASONS = {'inactividad': 'Inactividad', 'manual': 'Cierre manual', 'inactividad_previa_activacion': 'Inactiva antes de activar el cierre automático'}


class SupportError(ValueError):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def installed(c):
    return bool(c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='support_sessions'").fetchone())


def _iso(moment):
    return moment.isoformat(timespec='seconds')


def _dt(value):
    try:
        return datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


def settings(c):
    row = c.execute('SELECT value FROM system_state WHERE key=?', (KEY,)).fetchone()
    try:
        stored = json.loads(row['value']) if row else {}
    except (TypeError, ValueError):
        stored = {}
    out = json.loads(json.dumps(DEFAULTS))
    for k, v in stored.items():
        if k == 'channels' and isinstance(v, dict):
            for ch in out['channels']:
                out['channels'][ch].update({kk: bool(vv) for kk, vv in (v.get(ch) or {}).items() if kk in out['channels'][ch]})
        elif k in out:
            out[k] = v
    return out


def save_settings(c, data, user, now):
    cur = settings(c)
    new = json.loads(json.dumps(cur))
    try:
        for k in ('idle_seconds', 'visual_warning_seconds', 'client_warning_seconds', 'processing_limit_seconds', 'max_pause_minutes'):
            if k in data:
                new[k] = int(data[k])
    except (TypeError, ValueError):
        raise SupportError('Los tiempos deben ser números enteros.')
    if not 120 <= new['idle_seconds'] <= 3600:
        raise SupportError('El tiempo máximo de inactividad va de 2 a 60 minutos.')
    if not 0 < new['visual_warning_seconds'] < new['client_warning_seconds'] < new['idle_seconds']:
        raise SupportError('La advertencia visual debe ser anterior al aviso al cliente, y este anterior al cierre.')
    if not 10 <= new['processing_limit_seconds'] <= 300 or not 5 <= new['max_pause_minutes'] <= 240:
        raise SupportError('Procesamiento de ADI: 10 a 300 s; pausa máxima: 5 a 240 minutos.')
    for k in ('warning_text', 'close_text'):
        if k in data:
            text = ' '.join(str(data[k] or '').split())
            if not 20 <= len(text) <= 400:
                raise SupportError('Los mensajes automáticos deben tener entre 20 y 400 caracteres.')
            new[k] = text
    if 'reopen_auto' in data:
        new['reopen_auto'] = data['reopen_auto'] in (True, '1', 'true', 'on')
    for ch in new['channels']:
        for kk in ('warning', 'close_message'):
            key = '%s_%s' % (ch, kk)
            if key in data:
                new['channels'][ch][kk] = data[key] in (True, '1', 'true', 'on')
    c.execute('INSERT INTO system_state(key,value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value', (KEY, json.dumps(new, ensure_ascii=False)))
    changes = [k for k in new if new[k] != cur[k] and k != 'enabled']
    if changes and installed(c):
        _event(c, 0, 'configuracion', 'Cambios: ' + ', '.join(changes), user['id'], now, 'config:%s' % _iso(now) + ':' + ','.join(changes))
    return new


def _event(c, conv_id, kind, detail, user_id, now, idem):
    """Registro idempotente: la misma clave nunca se registra dos veces. Devuelve True si es nuevo."""
    try:
        c.execute('INSERT INTO support_events(conversation_id,kind,detail,user_id,created_at,idem) VALUES (?,?,?,?,?,?)',
                  (conv_id, kind, detail[:400], user_id, _iso(now), idem[:200]))
        return True
    except Exception:
        return False


def _channel(c, conv_id):
    try:
        return 'whatsapp' if c.execute('SELECT 1 FROM whatsapp_conversations WHERE conversation_id=?', (conv_id,)).fetchone() else 'web'
    except Exception:
        return 'web'


def session(c, conv_id):
    return c.execute('SELECT * FROM support_sessions WHERE conversation_id=?', (conv_id,)).fetchone()


def _ensure(c, conv_id, now, cfg):
    row = session(c, conv_id)
    if row:
        return row
    c.execute('INSERT OR IGNORE INTO support_sessions(conversation_id,channel,opened_at,last_activity_at,expires_at) VALUES (?,?,?,?,?)',
              (conv_id, _channel(c, conv_id), _iso(now), _iso(now), _iso(now + timedelta(seconds=cfg['idle_seconds']))))
    _event(c, conv_id, 'apertura', 'Sesión de atención abierta.', None, now, 'open:%d:%s' % (conv_id, _iso(now)))
    return session(c, conv_id)


def _post_public(c, conv_id, text, now):
    c.execute("INSERT INTO adi_messages(conversation_id,author,content,created_at) VALUES (?,'adi',?,?)", (conv_id, text, _iso(now)))


def activity(c, conv_id, who, now, message_id=None):
    """Actividad VÁLIDA (who: client | adi | human). Si la sesión había expirado, primero se cierra en su hora exacta y, si escribe el
    cliente, se reabre (sin duplicar por un mismo mensaje). Devuelve {'reopened': bool}."""
    if not installed(c):
        return {'reopened': False}
    cfg = settings(c)
    if not cfg['enabled']:
        return {'reopened': False}
    sweep_one(c, conv_id, now, cfg)
    row = _ensure(c, conv_id, now, cfg)
    reopened = False
    if row['status'] == 'cerrada':
        if who != 'client':
            return {'reopened': False}   # una respuesta del personal a una sesión cerrada no la reabre sola
        if not cfg['reopen_auto']:
            return {'reopened': False}
        if _event(c, conv_id, 'reapertura', 'El cliente volvió a escribir después del cierre.', None, now, 'reopen:%d:%s' % (conv_id, message_id or _iso(now))):
            c.execute("UPDATE support_sessions SET status='activa',closed_at='',effective_close_at='',close_reason='',close_kind='',closed_by=NULL,warned_at='',"
                      "reopened_count=reopened_count+1,opened_at=?,version=version+1 WHERE conversation_id=?", (_iso(now), conv_id))
            reopened = True
    field = {'client': 'last_client_at', 'adi': 'last_adi_at', 'human': 'last_human_at'}[who]
    first = ", first_response_at=CASE WHEN first_response_at='' AND last_client_at!='' THEN ? ELSE first_response_at END" if who in ('adi', 'human') else ''
    args = [_iso(now), _iso(now), who, _iso(now + timedelta(seconds=cfg['idle_seconds']))] + ([_iso(now)] if first else []) + [conv_id]
    c.execute('UPDATE support_sessions SET ' + field + '=?,last_activity_at=?,last_activity_by=?,expires_at=?,warned_at=\'\',processing_until=\'\',version=version+1'
              + first + ' WHERE conversation_id=?', args)
    return {'reopened': reopened}


def processing(c, conv_id, now, active=True):
    """ADI está generando una respuesta: no se cierra hasta processing_limit_seconds (nunca indefinidamente)."""
    if not installed(c) or not settings(c)['enabled']:
        return
    cfg = settings(c)
    _ensure(c, conv_id, now, cfg)
    c.execute('UPDATE support_sessions SET processing_until=? WHERE conversation_id=?',
              (_iso(now + timedelta(seconds=cfg['processing_limit_seconds'])) if active else '', conv_id))


def pause(c, conv_id, user, minutes, reason, now):
    cfg = settings(c)
    if not installed(c):
        raise SupportError(NOT_INSTALLED, 409)
    try:
        minutes = int(minutes)
    except (TypeError, ValueError):
        minutes = 0
    reason = ' '.join(str(reason or '').split())
    if not 1 <= minutes <= cfg['max_pause_minutes'] or not 10 <= len(reason) <= 300:
        raise SupportError('Indica minutos (1 a %d) y el motivo de la excepción (10 a 300 caracteres).' % cfg['max_pause_minutes'])
    _ensure(c, conv_id, now, cfg)
    c.execute('UPDATE support_sessions SET pause_until=?,pause_reason=?,paused_by=?,version=version+1 WHERE conversation_id=?',
              (_iso(now + timedelta(minutes=minutes)), reason, user['id'], conv_id))
    _event(c, conv_id, 'pausa', '%d min: %s' % (minutes, reason), user['id'], now, 'pause:%d:%s' % (conv_id, _iso(now)))


def close_manual(c, conv_id, user, now):
    if not installed(c):
        return
    cfg = settings(c)
    _ensure(c, conv_id, now, cfg)
    c.execute("UPDATE support_sessions SET status='cerrada',closed_at=?,effective_close_at=?,close_reason='manual',close_kind='manual',closed_by=?,version=version+1 "
              "WHERE conversation_id=? AND status='activa'", (_iso(now), _iso(now), user['id'], conv_id))
    _event(c, conv_id, 'cierre_manual', 'Finalizada por el personal.', user['id'], now, 'close-manual:%d:%s' % (conv_id, _iso(now)))


def reopen_manual(c, conv_id, user, now):
    if not installed(c):
        return
    cfg = settings(c)
    _ensure(c, conv_id, now, cfg)
    c.execute("UPDATE support_sessions SET status='activa',closed_at='',effective_close_at='',close_reason='',close_kind='',closed_by=NULL,warned_at='',"
              "reopened_count=reopened_count+1,last_activity_at=?,last_activity_by='human',expires_at=?,version=version+1 WHERE conversation_id=?",
              (_iso(now), _iso(now + timedelta(seconds=cfg['idle_seconds'])), conv_id))
    _event(c, conv_id, 'reapertura_manual', 'Reabierta por el personal.', user['id'], now, 'reopen-manual:%d:%s' % (conv_id, _iso(now)))


def _waiting_on_staff(row):
    """True si el último mensaje válido es del cliente: la inactividad es de PC-DOCTOR, no del cliente."""
    return row['last_activity_by'] == 'client'


def sweep_one(c, conv_id, now, cfg=None):
    """Evalúa una sesión: aviso previo (una sola vez) y cierre atómico al vencer. Devuelve el estado resultante o ''."""
    cfg = cfg or settings(c)
    row = session(c, conv_id)
    if not row or row['status'] != 'activa' or not cfg['enabled']:
        return row['status'] if row else ''
    exp = _dt(row['expires_at'])
    if not exp:
        return row['status']
    if row['processing_until'] and (_dt(row['processing_until']) or now) > now:
        return 'procesando'
    if row['pause_until'] and (_dt(row['pause_until']) or now) > now:
        return 'pausada'
    if _waiting_on_staff(row):
        if now >= exp:
            _event(c, conv_id, 'esperando_personal', 'El cliente espera respuesta desde %s: no se cierra por inactividad del personal.' % row['last_activity_at'],
                   None, now, 'waitstaff:%d:%s' % (conv_id, row['last_activity_at']))
        return 'esperando_personal'
    channel = cfg['channels'].get(row['channel'], {})
    warn_at = _dt(row['last_activity_at']) + timedelta(seconds=cfg['client_warning_seconds'])
    if now < exp and now >= warn_at and not row['warned_at']:
        if channel.get('warning') and _event(c, conv_id, 'aviso_cierre', 'Aviso previo de cierre.', None, now, 'warn:%d:%s' % (conv_id, row['last_activity_at'])):
            if row['channel'] == 'web':
                _post_public(c, conv_id, cfg['warning_text'], now)
        c.execute('UPDATE support_sessions SET warned_at=? WHERE conversation_id=? AND version=?', (_iso(now), conv_id, row['version']))
        return 'aviso'
    if now < exp:
        return 'activa'
    # Cierre atómico: solo si nadie la modificó desde que se leyó (version) y sigue vencida.
    cur = c.execute("UPDATE support_sessions SET status='cerrada',closed_at=?,effective_close_at=expires_at,close_reason='inactividad',close_kind='automatico',version=version+1 "
                    "WHERE conversation_id=? AND status='activa' AND version=? AND expires_at<=?", (_iso(now), conv_id, row['version'], _iso(now)))
    if getattr(cur, 'rowcount', 1) == 0:
        return 'activa'
    if _event(c, conv_id, 'cierre_automatico', 'Cerrada por inactividad (vencía %s).' % row['expires_at'], None, now, 'close:%d:%s' % (conv_id, row['expires_at'])):
        if channel.get('close_message') and row['channel'] == 'web':
            _post_public(c, conv_id, cfg['close_text'], _dt(row['expires_at']) or now)
    # La conversación se cierra; una solicitud de asesor pendiente (adi_handoffs) NO se toca: sigue pendiente para el personal.
    c.execute("UPDATE adi_conversations SET mode='closed' WHERE id=? AND mode!='closed'", (conv_id,))
    return 'cerrada'


def sweep(c, now, force=False):
    """Barrido de todas las sesiones vencidas o por avisar (como mucho cada SWEEP_GAP s salvo force). Seguro ante instancias simultáneas."""
    if not installed(c):
        return {'closed': 0, 'warned': 0}
    cfg = settings(c)
    if not cfg['enabled']:
        return {'closed': 0, 'warned': 0}
    if not force:
        row = c.execute('SELECT value FROM system_state WHERE key=?', (SWEEP_KEY,)).fetchone()
        last = _dt(row['value']) if row else None
        if last and (now - last).total_seconds() < SWEEP_GAP:
            return {'closed': 0, 'warned': 0, 'skipped': True}
    c.execute('INSERT INTO system_state(key,value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value', (SWEEP_KEY, _iso(now)))
    horizon = _iso(now + timedelta(seconds=cfg['idle_seconds'] - cfg['client_warning_seconds']))
    out = {'closed': 0, 'warned': 0}
    for (conv_id,) in c.execute("SELECT conversation_id FROM support_sessions WHERE status='activa' AND expires_at<=? ORDER BY expires_at LIMIT 200", (horizon,)).fetchall():
        result = sweep_one(c, conv_id, now, cfg)
        if result == 'cerrada':
            out['closed'] += 1
        elif result == 'aviso':
            out['warned'] += 1
    return out


def simulate_activation(c, now):
    """Qué pasaría al activar: conversaciones abiertas cuya última actividad pública supera el tiempo máximo. No cambia nada."""
    cfg = settings(c)
    rows = c.execute("SELECT v.id,v.mode,(SELECT MAX(created_at) FROM adi_messages m WHERE m.conversation_id=v.id AND m.visibility='public') last_at,"
                     "(SELECT author FROM adi_messages m WHERE m.conversation_id=v.id AND m.visibility='public' ORDER BY m.id DESC LIMIT 1) last_author "
                     "FROM adi_conversations v WHERE v.mode!='closed'").fetchall()
    limit = now - timedelta(seconds=cfg['idle_seconds'])
    closing, waiting, keep = [], [], []
    for r in rows:
        last = _dt(r['last_at']) if r['last_at'] else None
        item = {'id': r['id'], 'mode': r['mode'], 'last_at': r['last_at'] or '', 'last_author': r['last_author'] or ''}
        if last and last > limit:
            keep.append(item)
        elif r['last_author'] == 'client' and r['mode'] == 'human':
            waiting.append(item)
        else:
            closing.append(item)
    return {'would_close': len(closing), 'waiting_staff': len(waiting), 'kept_active': len(keep), 'sample': closing[:20], 'waiting': waiting[:20],
            'note': 'Al activar, las conversaciones antiguas se cierran en SILENCIO (sin avisos ni mensajes a clientes). Las que esperan respuesta del personal no se cierran.'}


def activate(c, user, now, confirm):
    if not installed(c):
        raise SupportError(NOT_INSTALLED, 409)
    if str(confirm or '').strip().upper() != 'ACTIVAR':
        raise SupportError('Escribe ACTIVAR para confirmar.')
    cfg = settings(c)
    sim = simulate_activation(c, now)
    limit = now - timedelta(seconds=cfg['idle_seconds'])
    closed = 0
    for r in c.execute("SELECT v.id,(SELECT MAX(created_at) FROM adi_messages m WHERE m.conversation_id=v.id AND m.visibility='public') last_at,"
                       "(SELECT author FROM adi_messages m WHERE m.conversation_id=v.id AND m.visibility='public' ORDER BY m.id DESC LIMIT 1) last_author,v.mode "
                       "FROM adi_conversations v WHERE v.mode!='closed'").fetchall():
        last = _dt(r['last_at']) if r['last_at'] else now
        who = 'client' if r['last_author'] == 'client' else 'adi'
        c.execute('INSERT OR IGNORE INTO support_sessions(conversation_id,channel,opened_at,last_activity_at,last_activity_by,expires_at) VALUES (?,?,?,?,?,?)',
                  (r['id'], _channel(c, r['id']), _iso(last), _iso(last), who, _iso(last + timedelta(seconds=cfg['idle_seconds']))))
        if last <= limit and not (who == 'client' and r['mode'] == 'human'):
            c.execute("UPDATE support_sessions SET status='cerrada',closed_at=?,effective_close_at=expires_at,close_reason='inactividad_previa_activacion',close_kind='automatico',"
                      "version=version+1 WHERE conversation_id=? AND status='activa'", (_iso(now), r['id']))
            c.execute("UPDATE adi_conversations SET mode='closed' WHERE id=?", (r['id'],))
            _event(c, r['id'], 'cierre_automatico', 'Cerrada en silencio al activar el cierre automático (inactiva desde %s).' % (r['last_at'] or '—'), user['id'], now,
                   'activation-close:%d' % r['id'])
            closed += 1
    cfg['enabled'] = True
    c.execute('INSERT INTO system_state(key,value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value', (KEY, json.dumps(cfg, ensure_ascii=False)))
    _event(c, 0, 'activacion', 'Cierre automático activado: %d cerradas en silencio, %d esperando al personal.' % (closed, sim['waiting_staff']), user['id'], now, 'activate:%s' % _iso(now))
    return {'closed_silently': closed, 'simulation': sim}


def deactivate(c, user, now):
    cfg = settings(c)
    cfg['enabled'] = False
    c.execute('INSERT INTO system_state(key,value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value', (KEY, json.dumps(cfg, ensure_ascii=False)))
    if installed(c):
        _event(c, 0, 'desactivacion', 'Cierre automático desactivado.', user['id'], now, 'deactivate:%s' % _iso(now))


def timer(c, conv_id, now):
    """Datos del contador visual (el servidor manda: expires_at)."""
    cfg = settings(c)
    row = session(c, conv_id) if installed(c) else None
    if not row:
        return {'enabled': cfg['enabled'], 'status': 'sin_sesion'}
    exp, last = _dt(row['expires_at']), _dt(row['last_activity_at'])
    remaining = max(0, int((exp - now).total_seconds())) if exp else None
    idle = max(0, int((now - last).total_seconds())) if last else None
    if row['status'] == 'cerrada':
        tone = 'gris'
    elif row['pause_until'] and (_dt(row['pause_until']) or now) > now:
        tone = 'verde'
    elif _waiting_on_staff(row):
        tone = 'amarillo'
    elif idle is not None and idle >= cfg['client_warning_seconds']:
        tone = 'rojo'
    elif idle is not None and idle >= cfg['visual_warning_seconds']:
        tone = 'amarillo'
    else:
        tone = 'verde'
    return {'enabled': cfg['enabled'], 'status': row['status'], 'tone': tone, 'idle_seconds': idle, 'remaining_seconds': remaining if row['status'] == 'activa' else 0,
            'limit_seconds': cfg['idle_seconds'], 'expires_at': row['expires_at'], 'last_activity_at': row['last_activity_at'], 'last_activity_by': row['last_activity_by'],
            'waiting_staff': _waiting_on_staff(row) and row['status'] == 'activa', 'paused_until': row['pause_until'], 'pause_reason': row['pause_reason'],
            'closed_at': row['effective_close_at'], 'close_reason': REASONS.get(row['close_reason'], row['close_reason']), 'close_kind': row['close_kind'],
            'reopened': row['reopened_count'], 'opened_at': row['opened_at']}


def metrics(c, now, days=7):
    """Indicadores reales (sesiones y eventos de los últimos `days` días)."""
    out = {'enabled': settings(c)['enabled']}
    if not installed(c):
        return out
    since = _iso(now - timedelta(days=days))
    ev = dict(c.execute('SELECT kind,COUNT(*) FROM support_events WHERE created_at>=? GROUP BY kind', (since,)).fetchall())
    firsts, resolutions = [], []
    for r in c.execute("SELECT opened_at,first_response_at,effective_close_at,last_client_at FROM support_sessions WHERE opened_at>=?", (since,)):
        a, f, z = _dt(r['opened_at']), _dt(r['first_response_at']), _dt(r['effective_close_at'])
        if a and f and f >= a:
            firsts.append((f - a).total_seconds())
        if a and z and z >= a:
            resolutions.append((z - a).total_seconds())
    out.update(closed_auto=ev.get('cierre_automatico', 0), closed_manual=ev.get('cierre_manual', 0), reopened=ev.get('reapertura', 0) + ev.get('reapertura_manual', 0),
               avg_first_response_s=round(sum(firsts) / len(firsts)) if firsts else None, avg_resolution_s=round(sum(resolutions) / len(resolutions)) if resolutions else None,
               days=days)
    return out


def events(c, conv_id=None, limit=40):
    if not installed(c):
        return []
    sql = 'SELECT e.*,COALESCE(u.name,\'Sistema\') user FROM support_events e LEFT JOIN users u ON u.id=e.user_id'
    args = ()
    if conv_id is not None:
        sql += ' WHERE e.conversation_id=?'
        args = (conv_id,)
    return [dict(r) for r in c.execute(sql + ' ORDER BY e.id DESC LIMIT ?', args + (limit,))]
