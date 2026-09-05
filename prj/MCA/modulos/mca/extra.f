# RTL del repo raiz que necesita mca, con rutas relativas a la RAIZ DEL
# REPO (ej: rtl/classic/axi_wr_fifo.v). Opcional: si el modulo no depende de
# nada de afuera, este archivo puede no existir.
#
# module.mk lo lee tambien cuando otro modulo declara a este en DEPS, asi que
# una dependencia arrastra las suyas sin que el modulo de arriba las repita.
