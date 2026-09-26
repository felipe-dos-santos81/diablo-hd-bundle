# NOTES

Live checks, spikes and runs of the Diablo animation kit, newest last.

## Extraction

The export (`../diablo-textures-exporter/out`, exporter 97939cd, DevilutionX 8bef7bc):
1,791 animations (1,056 player, 334 monster, 21 towner, 380 missile), 145,560
frames, every one on `levels/towndata/town.pal`; 182 monster animations carry 97
distinct TRNs (about 74,000 variant frames). `monsters/darkmage/dmagew.cl2`
has no frames. Layout at the defaults: 11,394 base sheets; 17,410 with
variants (11,386 packed); about 9.8 gigapixels of canvas a pass; 1,866 sheets
over 1 MP, the largest 1952x1440 (`monsters/nkr/nkrd.cl2`).
