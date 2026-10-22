# RTL del repo raiz. Rutas relativas a la RAIZ DEL REPO.
#
# El bus de sistema: lo necesita tb_sys_bus_proto, que es el unico TB del arbol
# que instancia el camino real (interconnect + un sys_bus_cdc por slot) en vez
# de un BFM que lo imita. La interfaz va primero: los otros tres la usan en los
# puertos.
rtl/interface/sys_bus_if.sv
rtl/sys_bus_cdc.sv
rtl/sys_bus_interconnect.sv
rtl/sys_bus_stub.sv
