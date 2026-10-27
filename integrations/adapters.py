"""Compatibilidad para lotes normalizados antiguos. Las APIs usan clients.py y sync.py."""

def join_normalized(enrollments, results):
    """Unión explícita por ID estable. Los resultados no cambian la identidad de matrícula."""
    rows={};allowed={'state','validated','certified_valid','employment','sector_relation','ccaa','priority','progress','evidence','company'}
    for e in enrollments:
        if not e.get('id') or e['id'] in rows:raise ValueError('ID de matrícula ausente o duplicado')
        rows[e['id']]=dict(e)
    for result in results:
        key=result.get('enrollment_id')
        if key not in rows:raise ValueError('Resultado sin matrícula asociada: '+str(key))
        rows[key].update({k:v for k,v in result.items() if k in allowed})
    return list(rows.values())
