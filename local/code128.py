"""Code 128 B/C, checksum módulo 103 y zona de silencio de 10 módulos.
Tabla de anchos definida por la simbología Code 128; sin dependencias de impresión.
"""
from functools import lru_cache
PATTERNS=['212222', '222122', '222221', '121223', '121322', '131222', '122213', '122312', '132212', '221213', '221312', '231212', '112232', '122132', '122231', '113222', '123122', '123221', '223211', '221132', '221231', '213212', '223112', '312131', '311222', '321122', '321221', '312212', '322112', '322211', '212123', '212321', '232121', '111323', '131123', '131321', '112313', '132113', '132311', '211313', '231113', '231311', '112133', '112331', '132131', '113123', '113321', '133121', '313121', '211331', '231131', '213113', '213311', '213131', '311123', '311321', '331121', '312113', '312311', '332111', '314111', '221411', '431111', '111224', '111422', '121124', '121421', '141122', '141221', '112214', '112412', '122114', '122411', '142112', '142211', '241211', '221114', '413111', '241112', '134111', '111242', '121142', '121241', '114212', '124112', '124211', '411212', '421112', '421211', '212141', '214121', '412121', '111143', '111341', '131141', '114113', '114311', '411113', '411311', '113141', '114131', '311141', '411131', '211412', '211214', '211232', '2331112']

def symbols(value):
    if not value or any(not 32<=ord(c)<=126 for c in value):raise ValueError('Identificador no compatible con Code 128.')
    @lru_cache(None)
    def tail(index,mode):
        if index==len(value):return ()
        options=[]
        b=(ord(value[index])-32,)+tail(index+1,'B')
        options.append(b if mode=='B' else (100,)+b)
        if index+1<len(value) and value[index:index+2].isdigit():
            c=(int(value[index:index+2]),)+tail(index+2,'C')
            options.append(c if mode=='C' else (99,)+c)
        return min(options,key=len)
    words=min(((104,)+tail(0,'B'),(105,)+tail(0,'C')),key=len)
    check=(words[0]+sum(i*w for i,w in enumerate(words[1:],1)))%103
    return words+(check,106)

def widths(value):
    return tuple(int(n) for word in symbols(value) for n in PATTERNS[word])
