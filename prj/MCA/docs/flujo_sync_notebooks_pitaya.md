# Flujo de trabajo — sincronizar notebooks de la RedPitaya

Los notebooks de `prj/MCA/software/*.ipynb` se **ejecutan en la RedPitaya**
(otra máquina, que corre Jupyter), no en la PC de desarrollo. Este documento
describe cómo traer los notebooks *ya ejecutados* — con sus outputs (texto y
plots) embebidos — de vuelta a la PC para revisarlos o para que Claude Code
los lea directamente sin copiar y pegar.

## Idea general

Un archivo `.ipynb` guarda las salidas de cada celda dentro del propio JSON
al hacer `Ctrl+S` en Jupyter. Por lo tanto, para "ver los resultados" alcanza
con traer el `.ipynb` guardado desde la Pitaya al repo local y abrirlo (o que
Claude lo lea: renderiza texto e imágenes de los outputs).

Hay **dos direcciones** de sincronización, no confundirlas:

| Dirección | Para qué | Comando |
|-----------|----------|---------|
| PC → Pitaya | desplegar el código a ejecutar | `rsync -avz --delete .../software/ root@<ip>:/home/jupyter/RedPitaya/remote_soft/` |
| Pitaya → PC | traer notebooks ejecutados | `rsync -avz pitaya:/home/jupyter/RedPitaya/remote_soft/*.ipynb .../software/` |

El *pull* (Pitaya → PC) trae **solo `.ipynb`** y **sin `--delete`**, así nunca
pisa ediciones locales de los `.py`. Si un mismo `.ipynb` se editó en las dos
puntas a la vez, gana el de la Pitaya.

## Acceso SSH

- Alias: `pitaya` (definido en `~/.ssh/config.d/pitaya`, incluido desde
  `~/.ssh/config` con `Include config.d/*`).
- Usuario `root`, clave dedicada `~/.ssh/id_ed25519_pi` (sin passphrase,
  exclusiva de la Pitaya — no reusa la de GitHub/FPGA).
- **La IP de la Pitaya cambia seguido** (histórico: .28 → .37 → .45). Cuando
  cambie, actualizar **solo** el campo `HostName` en `~/.ssh/config.d/pitaya`.

Verificar acceso:

```bash
ssh pitaya 'hostname'      # debe responder rp-xxxxxx sin pedir password
```

## Pasos

1. En Jupyter (en la Pitaya): correr las celdas y guardar con **`Ctrl+S`**
   (imprescindible: si no se guarda, el pull trae la versión sin outputs).
2. En la PC, traer los notebooks:

   ```bash
   rsync -avz pitaya:/home/jupyter/RedPitaya/remote_soft/*.ipynb \
     /home/lorenzo/PI/RedPitaya-FPGA/prj/MCA/software/
   ```

3. Abrir el `.ipynb` (o pedirle a Claude "traé/analizá X" — corre el rsync de
   arriba y lee los outputs directamente).

## Notas

- Rutas: en la Pitaya los notebooks viven en
  `/home/jupyter/RedPitaya/remote_soft/`; en la PC en `prj/MCA/software/`.
- Nada de este flujo toca el repo remoto de git; es solo copia de archivos
  entre la PC y la Pitaya por SSH.
