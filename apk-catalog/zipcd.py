import struct, urllib.request, zlib
UA={'User-Agent':'steam-frame-compat-scan/1.0'}
def rng(url, start, end=None):
    h=dict(UA); h['Range']=f'bytes={start}-' if end is None else f'bytes={start}-{end}'
    with urllib.request.urlopen(urllib.request.Request(url,headers=h),timeout=60) as r:
        return r.read()
def tail(url, n):
    h=dict(UA); h['Range']=f'bytes=-{n}'
    with urllib.request.urlopen(urllib.request.Request(url,headers=h),timeout=60) as r:
        return r.read()
def list_names(url, size):
    t=tail(url, min(size, 65557))
    i=t.rfind(b'PK\x05\x06')
    if i<0: raise ValueError('no EOCD')
    cd_size, cd_off = struct.unpack('<II', t[i+12:i+20])
    base=size-len(t)
    cd = t[cd_off-base:cd_off-base+cd_size] if cd_off>=base else rng(url, cd_off, cd_off+cd_size-1)
    names=[]; p=0; entries={}
    while p+46<=len(cd) and cd[p:p+4]==b'PK\x01\x02':
        comp,=struct.unpack('<H',cd[p+10:p+12])
        csize,usize=struct.unpack('<II',cd[p+20:p+28])
        nl,el,cl=struct.unpack('<HHH',cd[p+28:p+34]); lho,=struct.unpack('<I',cd[p+42:p+46])
        n=cd[p+46:p+46+nl].decode('utf-8','replace'); names.append(n); entries[n]=(comp,csize,lho)
        p+=46+nl+el+cl
    return names, entries, cd_size
def read_entry(url, entries, name):
    comp,csize,lho=entries[name]
    h=rng(url, lho, lho+29)
    nl,el=struct.unpack('<HH',h[26:30])
    data=rng(url, lho+30+nl+el, lho+30+nl+el+csize-1)
    return zlib.decompress(data,-15) if comp==8 else data
