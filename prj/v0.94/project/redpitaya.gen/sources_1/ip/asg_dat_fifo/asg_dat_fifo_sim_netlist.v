// Copyright 1986-2021 Xilinx, Inc. All Rights Reserved.
// --------------------------------------------------------------------------------
// Tool Version: Vivado v.2021.2 (lin64) Build 3367213 Tue Oct 19 02:47:39 MDT 2021
// Date        : Tue May 12 12:18:36 2026
// Host        : LoloVictus running 64-bit Ubuntu 20.04.3 LTS
// Command     : write_verilog -force -mode funcsim -rename_top asg_dat_fifo -prefix
//               asg_dat_fifo_ asg_dat_fifo_sim_netlist.v
// Design      : asg_dat_fifo
// Purpose     : This verilog netlist is a functional simulation representation of the design and should not be modified
//               or synthesized. This netlist cannot be used for SDF annotated simulation.
// Device      : xc7z020clg400-1
// --------------------------------------------------------------------------------
`timescale 1 ps / 1 ps

(* CHECK_LICENSE_TYPE = "asg_dat_fifo,fifo_generator_v13_2_6,{}" *) (* downgradeipidentifiedwarnings = "yes" *) (* x_core_info = "fifo_generator_v13_2_6,Vivado 2021.2" *) 
(* NotValidForBitStream *)
module asg_dat_fifo
   (rst,
    wr_clk,
    rd_clk,
    din,
    wr_en,
    rd_en,
    dout,
    full,
    empty,
    rd_data_count,
    wr_rst_busy,
    rd_rst_busy);
  input rst;
  (* x_interface_info = "xilinx.com:signal:clock:1.0 write_clk CLK" *) (* x_interface_parameter = "XIL_INTERFACENAME write_clk, FREQ_HZ 100000000, FREQ_TOLERANCE_HZ 0, PHASE 0.0, INSERT_VIP 0" *) input wr_clk;
  (* x_interface_info = "xilinx.com:signal:clock:1.0 read_clk CLK" *) (* x_interface_parameter = "XIL_INTERFACENAME read_clk, FREQ_HZ 100000000, FREQ_TOLERANCE_HZ 0, PHASE 0.0, INSERT_VIP 0" *) input rd_clk;
  (* x_interface_info = "xilinx.com:interface:fifo_write:1.0 FIFO_WRITE WR_DATA" *) input [95:0]din;
  (* x_interface_info = "xilinx.com:interface:fifo_write:1.0 FIFO_WRITE WR_EN" *) input wr_en;
  (* x_interface_info = "xilinx.com:interface:fifo_read:1.0 FIFO_READ RD_EN" *) input rd_en;
  (* x_interface_info = "xilinx.com:interface:fifo_read:1.0 FIFO_READ RD_DATA" *) output [95:0]dout;
  (* x_interface_info = "xilinx.com:interface:fifo_write:1.0 FIFO_WRITE FULL" *) output full;
  (* x_interface_info = "xilinx.com:interface:fifo_read:1.0 FIFO_READ EMPTY" *) output empty;
  output [7:0]rd_data_count;
  output wr_rst_busy;
  output rd_rst_busy;

  wire [95:0]din;
  wire [95:0]dout;
  wire empty;
  wire full;
  wire rd_clk;
  wire [7:0]rd_data_count;
  wire rd_en;
  wire rd_rst_busy;
  wire rst;
  wire wr_clk;
  wire wr_en;
  wire wr_rst_busy;
  wire NLW_U0_almost_empty_UNCONNECTED;
  wire NLW_U0_almost_full_UNCONNECTED;
  wire NLW_U0_axi_ar_dbiterr_UNCONNECTED;
  wire NLW_U0_axi_ar_overflow_UNCONNECTED;
  wire NLW_U0_axi_ar_prog_empty_UNCONNECTED;
  wire NLW_U0_axi_ar_prog_full_UNCONNECTED;
  wire NLW_U0_axi_ar_sbiterr_UNCONNECTED;
  wire NLW_U0_axi_ar_underflow_UNCONNECTED;
  wire NLW_U0_axi_aw_dbiterr_UNCONNECTED;
  wire NLW_U0_axi_aw_overflow_UNCONNECTED;
  wire NLW_U0_axi_aw_prog_empty_UNCONNECTED;
  wire NLW_U0_axi_aw_prog_full_UNCONNECTED;
  wire NLW_U0_axi_aw_sbiterr_UNCONNECTED;
  wire NLW_U0_axi_aw_underflow_UNCONNECTED;
  wire NLW_U0_axi_b_dbiterr_UNCONNECTED;
  wire NLW_U0_axi_b_overflow_UNCONNECTED;
  wire NLW_U0_axi_b_prog_empty_UNCONNECTED;
  wire NLW_U0_axi_b_prog_full_UNCONNECTED;
  wire NLW_U0_axi_b_sbiterr_UNCONNECTED;
  wire NLW_U0_axi_b_underflow_UNCONNECTED;
  wire NLW_U0_axi_r_dbiterr_UNCONNECTED;
  wire NLW_U0_axi_r_overflow_UNCONNECTED;
  wire NLW_U0_axi_r_prog_empty_UNCONNECTED;
  wire NLW_U0_axi_r_prog_full_UNCONNECTED;
  wire NLW_U0_axi_r_sbiterr_UNCONNECTED;
  wire NLW_U0_axi_r_underflow_UNCONNECTED;
  wire NLW_U0_axi_w_dbiterr_UNCONNECTED;
  wire NLW_U0_axi_w_overflow_UNCONNECTED;
  wire NLW_U0_axi_w_prog_empty_UNCONNECTED;
  wire NLW_U0_axi_w_prog_full_UNCONNECTED;
  wire NLW_U0_axi_w_sbiterr_UNCONNECTED;
  wire NLW_U0_axi_w_underflow_UNCONNECTED;
  wire NLW_U0_axis_dbiterr_UNCONNECTED;
  wire NLW_U0_axis_overflow_UNCONNECTED;
  wire NLW_U0_axis_prog_empty_UNCONNECTED;
  wire NLW_U0_axis_prog_full_UNCONNECTED;
  wire NLW_U0_axis_sbiterr_UNCONNECTED;
  wire NLW_U0_axis_underflow_UNCONNECTED;
  wire NLW_U0_dbiterr_UNCONNECTED;
  wire NLW_U0_m_axi_arvalid_UNCONNECTED;
  wire NLW_U0_m_axi_awvalid_UNCONNECTED;
  wire NLW_U0_m_axi_bready_UNCONNECTED;
  wire NLW_U0_m_axi_rready_UNCONNECTED;
  wire NLW_U0_m_axi_wlast_UNCONNECTED;
  wire NLW_U0_m_axi_wvalid_UNCONNECTED;
  wire NLW_U0_m_axis_tlast_UNCONNECTED;
  wire NLW_U0_m_axis_tvalid_UNCONNECTED;
  wire NLW_U0_overflow_UNCONNECTED;
  wire NLW_U0_prog_empty_UNCONNECTED;
  wire NLW_U0_prog_full_UNCONNECTED;
  wire NLW_U0_s_axi_arready_UNCONNECTED;
  wire NLW_U0_s_axi_awready_UNCONNECTED;
  wire NLW_U0_s_axi_bvalid_UNCONNECTED;
  wire NLW_U0_s_axi_rlast_UNCONNECTED;
  wire NLW_U0_s_axi_rvalid_UNCONNECTED;
  wire NLW_U0_s_axi_wready_UNCONNECTED;
  wire NLW_U0_s_axis_tready_UNCONNECTED;
  wire NLW_U0_sbiterr_UNCONNECTED;
  wire NLW_U0_underflow_UNCONNECTED;
  wire NLW_U0_valid_UNCONNECTED;
  wire NLW_U0_wr_ack_UNCONNECTED;
  wire [4:0]NLW_U0_axi_ar_data_count_UNCONNECTED;
  wire [4:0]NLW_U0_axi_ar_rd_data_count_UNCONNECTED;
  wire [4:0]NLW_U0_axi_ar_wr_data_count_UNCONNECTED;
  wire [4:0]NLW_U0_axi_aw_data_count_UNCONNECTED;
  wire [4:0]NLW_U0_axi_aw_rd_data_count_UNCONNECTED;
  wire [4:0]NLW_U0_axi_aw_wr_data_count_UNCONNECTED;
  wire [4:0]NLW_U0_axi_b_data_count_UNCONNECTED;
  wire [4:0]NLW_U0_axi_b_rd_data_count_UNCONNECTED;
  wire [4:0]NLW_U0_axi_b_wr_data_count_UNCONNECTED;
  wire [10:0]NLW_U0_axi_r_data_count_UNCONNECTED;
  wire [10:0]NLW_U0_axi_r_rd_data_count_UNCONNECTED;
  wire [10:0]NLW_U0_axi_r_wr_data_count_UNCONNECTED;
  wire [10:0]NLW_U0_axi_w_data_count_UNCONNECTED;
  wire [10:0]NLW_U0_axi_w_rd_data_count_UNCONNECTED;
  wire [10:0]NLW_U0_axi_w_wr_data_count_UNCONNECTED;
  wire [10:0]NLW_U0_axis_data_count_UNCONNECTED;
  wire [10:0]NLW_U0_axis_rd_data_count_UNCONNECTED;
  wire [10:0]NLW_U0_axis_wr_data_count_UNCONNECTED;
  wire [7:0]NLW_U0_data_count_UNCONNECTED;
  wire [31:0]NLW_U0_m_axi_araddr_UNCONNECTED;
  wire [1:0]NLW_U0_m_axi_arburst_UNCONNECTED;
  wire [3:0]NLW_U0_m_axi_arcache_UNCONNECTED;
  wire [0:0]NLW_U0_m_axi_arid_UNCONNECTED;
  wire [7:0]NLW_U0_m_axi_arlen_UNCONNECTED;
  wire [0:0]NLW_U0_m_axi_arlock_UNCONNECTED;
  wire [2:0]NLW_U0_m_axi_arprot_UNCONNECTED;
  wire [3:0]NLW_U0_m_axi_arqos_UNCONNECTED;
  wire [3:0]NLW_U0_m_axi_arregion_UNCONNECTED;
  wire [2:0]NLW_U0_m_axi_arsize_UNCONNECTED;
  wire [0:0]NLW_U0_m_axi_aruser_UNCONNECTED;
  wire [31:0]NLW_U0_m_axi_awaddr_UNCONNECTED;
  wire [1:0]NLW_U0_m_axi_awburst_UNCONNECTED;
  wire [3:0]NLW_U0_m_axi_awcache_UNCONNECTED;
  wire [0:0]NLW_U0_m_axi_awid_UNCONNECTED;
  wire [7:0]NLW_U0_m_axi_awlen_UNCONNECTED;
  wire [0:0]NLW_U0_m_axi_awlock_UNCONNECTED;
  wire [2:0]NLW_U0_m_axi_awprot_UNCONNECTED;
  wire [3:0]NLW_U0_m_axi_awqos_UNCONNECTED;
  wire [3:0]NLW_U0_m_axi_awregion_UNCONNECTED;
  wire [2:0]NLW_U0_m_axi_awsize_UNCONNECTED;
  wire [0:0]NLW_U0_m_axi_awuser_UNCONNECTED;
  wire [63:0]NLW_U0_m_axi_wdata_UNCONNECTED;
  wire [0:0]NLW_U0_m_axi_wid_UNCONNECTED;
  wire [7:0]NLW_U0_m_axi_wstrb_UNCONNECTED;
  wire [0:0]NLW_U0_m_axi_wuser_UNCONNECTED;
  wire [7:0]NLW_U0_m_axis_tdata_UNCONNECTED;
  wire [0:0]NLW_U0_m_axis_tdest_UNCONNECTED;
  wire [0:0]NLW_U0_m_axis_tid_UNCONNECTED;
  wire [0:0]NLW_U0_m_axis_tkeep_UNCONNECTED;
  wire [0:0]NLW_U0_m_axis_tstrb_UNCONNECTED;
  wire [3:0]NLW_U0_m_axis_tuser_UNCONNECTED;
  wire [0:0]NLW_U0_s_axi_bid_UNCONNECTED;
  wire [1:0]NLW_U0_s_axi_bresp_UNCONNECTED;
  wire [0:0]NLW_U0_s_axi_buser_UNCONNECTED;
  wire [63:0]NLW_U0_s_axi_rdata_UNCONNECTED;
  wire [0:0]NLW_U0_s_axi_rid_UNCONNECTED;
  wire [1:0]NLW_U0_s_axi_rresp_UNCONNECTED;
  wire [0:0]NLW_U0_s_axi_ruser_UNCONNECTED;
  wire [7:0]NLW_U0_wr_data_count_UNCONNECTED;

  (* C_ADD_NGC_CONSTRAINT = "0" *) 
  (* C_APPLICATION_TYPE_AXIS = "0" *) 
  (* C_APPLICATION_TYPE_RACH = "0" *) 
  (* C_APPLICATION_TYPE_RDCH = "0" *) 
  (* C_APPLICATION_TYPE_WACH = "0" *) 
  (* C_APPLICATION_TYPE_WDCH = "0" *) 
  (* C_APPLICATION_TYPE_WRCH = "0" *) 
  (* C_AXIS_TDATA_WIDTH = "8" *) 
  (* C_AXIS_TDEST_WIDTH = "1" *) 
  (* C_AXIS_TID_WIDTH = "1" *) 
  (* C_AXIS_TKEEP_WIDTH = "1" *) 
  (* C_AXIS_TSTRB_WIDTH = "1" *) 
  (* C_AXIS_TUSER_WIDTH = "4" *) 
  (* C_AXIS_TYPE = "0" *) 
  (* C_AXI_ADDR_WIDTH = "32" *) 
  (* C_AXI_ARUSER_WIDTH = "1" *) 
  (* C_AXI_AWUSER_WIDTH = "1" *) 
  (* C_AXI_BUSER_WIDTH = "1" *) 
  (* C_AXI_DATA_WIDTH = "64" *) 
  (* C_AXI_ID_WIDTH = "1" *) 
  (* C_AXI_LEN_WIDTH = "8" *) 
  (* C_AXI_LOCK_WIDTH = "1" *) 
  (* C_AXI_RUSER_WIDTH = "1" *) 
  (* C_AXI_TYPE = "1" *) 
  (* C_AXI_WUSER_WIDTH = "1" *) 
  (* C_COMMON_CLOCK = "0" *) 
  (* C_COUNT_TYPE = "0" *) 
  (* C_DATA_COUNT_WIDTH = "8" *) 
  (* C_DEFAULT_VALUE = "BlankString" *) 
  (* C_DIN_WIDTH = "96" *) 
  (* C_DIN_WIDTH_AXIS = "1" *) 
  (* C_DIN_WIDTH_RACH = "32" *) 
  (* C_DIN_WIDTH_RDCH = "64" *) 
  (* C_DIN_WIDTH_WACH = "1" *) 
  (* C_DIN_WIDTH_WDCH = "64" *) 
  (* C_DIN_WIDTH_WRCH = "2" *) 
  (* C_DOUT_RST_VAL = "0" *) 
  (* C_DOUT_WIDTH = "96" *) 
  (* C_ENABLE_RLOCS = "0" *) 
  (* C_ENABLE_RST_SYNC = "1" *) 
  (* C_EN_SAFETY_CKT = "1" *) 
  (* C_ERROR_INJECTION_TYPE = "0" *) 
  (* C_ERROR_INJECTION_TYPE_AXIS = "0" *) 
  (* C_ERROR_INJECTION_TYPE_RACH = "0" *) 
  (* C_ERROR_INJECTION_TYPE_RDCH = "0" *) 
  (* C_ERROR_INJECTION_TYPE_WACH = "0" *) 
  (* C_ERROR_INJECTION_TYPE_WDCH = "0" *) 
  (* C_ERROR_INJECTION_TYPE_WRCH = "0" *) 
  (* C_FAMILY = "zynq" *) 
  (* C_FULL_FLAGS_RST_VAL = "1" *) 
  (* C_HAS_ALMOST_EMPTY = "0" *) 
  (* C_HAS_ALMOST_FULL = "0" *) 
  (* C_HAS_AXIS_TDATA = "1" *) 
  (* C_HAS_AXIS_TDEST = "0" *) 
  (* C_HAS_AXIS_TID = "0" *) 
  (* C_HAS_AXIS_TKEEP = "0" *) 
  (* C_HAS_AXIS_TLAST = "0" *) 
  (* C_HAS_AXIS_TREADY = "1" *) 
  (* C_HAS_AXIS_TSTRB = "0" *) 
  (* C_HAS_AXIS_TUSER = "1" *) 
  (* C_HAS_AXI_ARUSER = "0" *) 
  (* C_HAS_AXI_AWUSER = "0" *) 
  (* C_HAS_AXI_BUSER = "0" *) 
  (* C_HAS_AXI_ID = "0" *) 
  (* C_HAS_AXI_RD_CHANNEL = "1" *) 
  (* C_HAS_AXI_RUSER = "0" *) 
  (* C_HAS_AXI_WR_CHANNEL = "1" *) 
  (* C_HAS_AXI_WUSER = "0" *) 
  (* C_HAS_BACKUP = "0" *) 
  (* C_HAS_DATA_COUNT = "0" *) 
  (* C_HAS_DATA_COUNTS_AXIS = "0" *) 
  (* C_HAS_DATA_COUNTS_RACH = "0" *) 
  (* C_HAS_DATA_COUNTS_RDCH = "0" *) 
  (* C_HAS_DATA_COUNTS_WACH = "0" *) 
  (* C_HAS_DATA_COUNTS_WDCH = "0" *) 
  (* C_HAS_DATA_COUNTS_WRCH = "0" *) 
  (* C_HAS_INT_CLK = "0" *) 
  (* C_HAS_MASTER_CE = "0" *) 
  (* C_HAS_MEMINIT_FILE = "0" *) 
  (* C_HAS_OVERFLOW = "0" *) 
  (* C_HAS_PROG_FLAGS_AXIS = "0" *) 
  (* C_HAS_PROG_FLAGS_RACH = "0" *) 
  (* C_HAS_PROG_FLAGS_RDCH = "0" *) 
  (* C_HAS_PROG_FLAGS_WACH = "0" *) 
  (* C_HAS_PROG_FLAGS_WDCH = "0" *) 
  (* C_HAS_PROG_FLAGS_WRCH = "0" *) 
  (* C_HAS_RD_DATA_COUNT = "1" *) 
  (* C_HAS_RD_RST = "0" *) 
  (* C_HAS_RST = "1" *) 
  (* C_HAS_SLAVE_CE = "0" *) 
  (* C_HAS_SRST = "0" *) 
  (* C_HAS_UNDERFLOW = "0" *) 
  (* C_HAS_VALID = "0" *) 
  (* C_HAS_WR_ACK = "0" *) 
  (* C_HAS_WR_DATA_COUNT = "0" *) 
  (* C_HAS_WR_RST = "0" *) 
  (* C_IMPLEMENTATION_TYPE = "2" *) 
  (* C_IMPLEMENTATION_TYPE_AXIS = "1" *) 
  (* C_IMPLEMENTATION_TYPE_RACH = "2" *) 
  (* C_IMPLEMENTATION_TYPE_RDCH = "1" *) 
  (* C_IMPLEMENTATION_TYPE_WACH = "2" *) 
  (* C_IMPLEMENTATION_TYPE_WDCH = "1" *) 
  (* C_IMPLEMENTATION_TYPE_WRCH = "2" *) 
  (* C_INIT_WR_PNTR_VAL = "0" *) 
  (* C_INTERFACE_TYPE = "0" *) 
  (* C_MEMORY_TYPE = "1" *) 
  (* C_MIF_FILE_NAME = "BlankString" *) 
  (* C_MSGON_VAL = "1" *) 
  (* C_OPTIMIZATION_MODE = "0" *) 
  (* C_OVERFLOW_LOW = "0" *) 
  (* C_POWER_SAVING_MODE = "0" *) 
  (* C_PRELOAD_LATENCY = "2" *) 
  (* C_PRELOAD_REGS = "1" *) 
  (* C_PRIM_FIFO_TYPE = "512x72" *) 
  (* C_PRIM_FIFO_TYPE_AXIS = "1kx18" *) 
  (* C_PRIM_FIFO_TYPE_RACH = "512x36" *) 
  (* C_PRIM_FIFO_TYPE_RDCH = "1kx36" *) 
  (* C_PRIM_FIFO_TYPE_WACH = "512x36" *) 
  (* C_PRIM_FIFO_TYPE_WDCH = "1kx36" *) 
  (* C_PRIM_FIFO_TYPE_WRCH = "512x36" *) 
  (* C_PROG_EMPTY_THRESH_ASSERT_VAL = "2" *) 
  (* C_PROG_EMPTY_THRESH_ASSERT_VAL_AXIS = "1022" *) 
  (* C_PROG_EMPTY_THRESH_ASSERT_VAL_RACH = "1022" *) 
  (* C_PROG_EMPTY_THRESH_ASSERT_VAL_RDCH = "1022" *) 
  (* C_PROG_EMPTY_THRESH_ASSERT_VAL_WACH = "1022" *) 
  (* C_PROG_EMPTY_THRESH_ASSERT_VAL_WDCH = "1022" *) 
  (* C_PROG_EMPTY_THRESH_ASSERT_VAL_WRCH = "1022" *) 
  (* C_PROG_EMPTY_THRESH_NEGATE_VAL = "3" *) 
  (* C_PROG_EMPTY_TYPE = "0" *) 
  (* C_PROG_EMPTY_TYPE_AXIS = "0" *) 
  (* C_PROG_EMPTY_TYPE_RACH = "0" *) 
  (* C_PROG_EMPTY_TYPE_RDCH = "0" *) 
  (* C_PROG_EMPTY_TYPE_WACH = "0" *) 
  (* C_PROG_EMPTY_TYPE_WDCH = "0" *) 
  (* C_PROG_EMPTY_TYPE_WRCH = "0" *) 
  (* C_PROG_FULL_THRESH_ASSERT_VAL = "253" *) 
  (* C_PROG_FULL_THRESH_ASSERT_VAL_AXIS = "1023" *) 
  (* C_PROG_FULL_THRESH_ASSERT_VAL_RACH = "1023" *) 
  (* C_PROG_FULL_THRESH_ASSERT_VAL_RDCH = "1023" *) 
  (* C_PROG_FULL_THRESH_ASSERT_VAL_WACH = "1023" *) 
  (* C_PROG_FULL_THRESH_ASSERT_VAL_WDCH = "1023" *) 
  (* C_PROG_FULL_THRESH_ASSERT_VAL_WRCH = "1023" *) 
  (* C_PROG_FULL_THRESH_NEGATE_VAL = "252" *) 
  (* C_PROG_FULL_TYPE = "0" *) 
  (* C_PROG_FULL_TYPE_AXIS = "0" *) 
  (* C_PROG_FULL_TYPE_RACH = "0" *) 
  (* C_PROG_FULL_TYPE_RDCH = "0" *) 
  (* C_PROG_FULL_TYPE_WACH = "0" *) 
  (* C_PROG_FULL_TYPE_WDCH = "0" *) 
  (* C_PROG_FULL_TYPE_WRCH = "0" *) 
  (* C_RACH_TYPE = "0" *) 
  (* C_RDCH_TYPE = "0" *) 
  (* C_RD_DATA_COUNT_WIDTH = "8" *) 
  (* C_RD_DEPTH = "256" *) 
  (* C_RD_FREQ = "1" *) 
  (* C_RD_PNTR_WIDTH = "8" *) 
  (* C_REG_SLICE_MODE_AXIS = "0" *) 
  (* C_REG_SLICE_MODE_RACH = "0" *) 
  (* C_REG_SLICE_MODE_RDCH = "0" *) 
  (* C_REG_SLICE_MODE_WACH = "0" *) 
  (* C_REG_SLICE_MODE_WDCH = "0" *) 
  (* C_REG_SLICE_MODE_WRCH = "0" *) 
  (* C_SELECT_XPM = "0" *) 
  (* C_SYNCHRONIZER_STAGE = "2" *) 
  (* C_UNDERFLOW_LOW = "0" *) 
  (* C_USE_COMMON_OVERFLOW = "0" *) 
  (* C_USE_COMMON_UNDERFLOW = "0" *) 
  (* C_USE_DEFAULT_SETTINGS = "0" *) 
  (* C_USE_DOUT_RST = "1" *) 
  (* C_USE_ECC = "0" *) 
  (* C_USE_ECC_AXIS = "0" *) 
  (* C_USE_ECC_RACH = "0" *) 
  (* C_USE_ECC_RDCH = "0" *) 
  (* C_USE_ECC_WACH = "0" *) 
  (* C_USE_ECC_WDCH = "0" *) 
  (* C_USE_ECC_WRCH = "0" *) 
  (* C_USE_EMBEDDED_REG = "1" *) 
  (* C_USE_FIFO16_FLAGS = "0" *) 
  (* C_USE_FWFT_DATA_COUNT = "0" *) 
  (* C_USE_PIPELINE_REG = "0" *) 
  (* C_VALID_LOW = "0" *) 
  (* C_WACH_TYPE = "0" *) 
  (* C_WDCH_TYPE = "0" *) 
  (* C_WRCH_TYPE = "0" *) 
  (* C_WR_ACK_LOW = "0" *) 
  (* C_WR_DATA_COUNT_WIDTH = "8" *) 
  (* C_WR_DEPTH = "256" *) 
  (* C_WR_DEPTH_AXIS = "1024" *) 
  (* C_WR_DEPTH_RACH = "16" *) 
  (* C_WR_DEPTH_RDCH = "1024" *) 
  (* C_WR_DEPTH_WACH = "16" *) 
  (* C_WR_DEPTH_WDCH = "1024" *) 
  (* C_WR_DEPTH_WRCH = "16" *) 
  (* C_WR_FREQ = "1" *) 
  (* C_WR_PNTR_WIDTH = "8" *) 
  (* C_WR_PNTR_WIDTH_AXIS = "10" *) 
  (* C_WR_PNTR_WIDTH_RACH = "4" *) 
  (* C_WR_PNTR_WIDTH_RDCH = "10" *) 
  (* C_WR_PNTR_WIDTH_WACH = "4" *) 
  (* C_WR_PNTR_WIDTH_WDCH = "10" *) 
  (* C_WR_PNTR_WIDTH_WRCH = "4" *) 
  (* C_WR_RESPONSE_LATENCY = "1" *) 
  (* is_du_within_envelope = "true" *) 
  asg_dat_fifo_fifo_generator_v13_2_6 U0
       (.almost_empty(NLW_U0_almost_empty_UNCONNECTED),
        .almost_full(NLW_U0_almost_full_UNCONNECTED),
        .axi_ar_data_count(NLW_U0_axi_ar_data_count_UNCONNECTED[4:0]),
        .axi_ar_dbiterr(NLW_U0_axi_ar_dbiterr_UNCONNECTED),
        .axi_ar_injectdbiterr(1'b0),
        .axi_ar_injectsbiterr(1'b0),
        .axi_ar_overflow(NLW_U0_axi_ar_overflow_UNCONNECTED),
        .axi_ar_prog_empty(NLW_U0_axi_ar_prog_empty_UNCONNECTED),
        .axi_ar_prog_empty_thresh({1'b0,1'b0,1'b0,1'b0}),
        .axi_ar_prog_full(NLW_U0_axi_ar_prog_full_UNCONNECTED),
        .axi_ar_prog_full_thresh({1'b0,1'b0,1'b0,1'b0}),
        .axi_ar_rd_data_count(NLW_U0_axi_ar_rd_data_count_UNCONNECTED[4:0]),
        .axi_ar_sbiterr(NLW_U0_axi_ar_sbiterr_UNCONNECTED),
        .axi_ar_underflow(NLW_U0_axi_ar_underflow_UNCONNECTED),
        .axi_ar_wr_data_count(NLW_U0_axi_ar_wr_data_count_UNCONNECTED[4:0]),
        .axi_aw_data_count(NLW_U0_axi_aw_data_count_UNCONNECTED[4:0]),
        .axi_aw_dbiterr(NLW_U0_axi_aw_dbiterr_UNCONNECTED),
        .axi_aw_injectdbiterr(1'b0),
        .axi_aw_injectsbiterr(1'b0),
        .axi_aw_overflow(NLW_U0_axi_aw_overflow_UNCONNECTED),
        .axi_aw_prog_empty(NLW_U0_axi_aw_prog_empty_UNCONNECTED),
        .axi_aw_prog_empty_thresh({1'b0,1'b0,1'b0,1'b0}),
        .axi_aw_prog_full(NLW_U0_axi_aw_prog_full_UNCONNECTED),
        .axi_aw_prog_full_thresh({1'b0,1'b0,1'b0,1'b0}),
        .axi_aw_rd_data_count(NLW_U0_axi_aw_rd_data_count_UNCONNECTED[4:0]),
        .axi_aw_sbiterr(NLW_U0_axi_aw_sbiterr_UNCONNECTED),
        .axi_aw_underflow(NLW_U0_axi_aw_underflow_UNCONNECTED),
        .axi_aw_wr_data_count(NLW_U0_axi_aw_wr_data_count_UNCONNECTED[4:0]),
        .axi_b_data_count(NLW_U0_axi_b_data_count_UNCONNECTED[4:0]),
        .axi_b_dbiterr(NLW_U0_axi_b_dbiterr_UNCONNECTED),
        .axi_b_injectdbiterr(1'b0),
        .axi_b_injectsbiterr(1'b0),
        .axi_b_overflow(NLW_U0_axi_b_overflow_UNCONNECTED),
        .axi_b_prog_empty(NLW_U0_axi_b_prog_empty_UNCONNECTED),
        .axi_b_prog_empty_thresh({1'b0,1'b0,1'b0,1'b0}),
        .axi_b_prog_full(NLW_U0_axi_b_prog_full_UNCONNECTED),
        .axi_b_prog_full_thresh({1'b0,1'b0,1'b0,1'b0}),
        .axi_b_rd_data_count(NLW_U0_axi_b_rd_data_count_UNCONNECTED[4:0]),
        .axi_b_sbiterr(NLW_U0_axi_b_sbiterr_UNCONNECTED),
        .axi_b_underflow(NLW_U0_axi_b_underflow_UNCONNECTED),
        .axi_b_wr_data_count(NLW_U0_axi_b_wr_data_count_UNCONNECTED[4:0]),
        .axi_r_data_count(NLW_U0_axi_r_data_count_UNCONNECTED[10:0]),
        .axi_r_dbiterr(NLW_U0_axi_r_dbiterr_UNCONNECTED),
        .axi_r_injectdbiterr(1'b0),
        .axi_r_injectsbiterr(1'b0),
        .axi_r_overflow(NLW_U0_axi_r_overflow_UNCONNECTED),
        .axi_r_prog_empty(NLW_U0_axi_r_prog_empty_UNCONNECTED),
        .axi_r_prog_empty_thresh({1'b0,1'b0,1'b0,1'b0,1'b0,1'b0,1'b0,1'b0,1'b0,1'b0}),
        .axi_r_prog_full(NLW_U0_axi_r_prog_full_UNCONNECTED),
        .axi_r_prog_full_thresh({1'b0,1'b0,1'b0,1'b0,1'b0,1'b0,1'b0,1'b0,1'b0,1'b0}),
        .axi_r_rd_data_count(NLW_U0_axi_r_rd_data_count_UNCONNECTED[10:0]),
        .axi_r_sbiterr(NLW_U0_axi_r_sbiterr_UNCONNECTED),
        .axi_r_underflow(NLW_U0_axi_r_underflow_UNCONNECTED),
        .axi_r_wr_data_count(NLW_U0_axi_r_wr_data_count_UNCONNECTED[10:0]),
        .axi_w_data_count(NLW_U0_axi_w_data_count_UNCONNECTED[10:0]),
        .axi_w_dbiterr(NLW_U0_axi_w_dbiterr_UNCONNECTED),
        .axi_w_injectdbiterr(1'b0),
        .axi_w_injectsbiterr(1'b0),
        .axi_w_overflow(NLW_U0_axi_w_overflow_UNCONNECTED),
        .axi_w_prog_empty(NLW_U0_axi_w_prog_empty_UNCONNECTED),
        .axi_w_prog_empty_thresh({1'b0,1'b0,1'b0,1'b0,1'b0,1'b0,1'b0,1'b0,1'b0,1'b0}),
        .axi_w_prog_full(NLW_U0_axi_w_prog_full_UNCONNECTED),
        .axi_w_prog_full_thresh({1'b0,1'b0,1'b0,1'b0,1'b0,1'b0,1'b0,1'b0,1'b0,1'b0}),
        .axi_w_rd_data_count(NLW_U0_axi_w_rd_data_count_UNCONNECTED[10:0]),
        .axi_w_sbiterr(NLW_U0_axi_w_sbiterr_UNCONNECTED),
        .axi_w_underflow(NLW_U0_axi_w_underflow_UNCONNECTED),
        .axi_w_wr_data_count(NLW_U0_axi_w_wr_data_count_UNCONNECTED[10:0]),
        .axis_data_count(NLW_U0_axis_data_count_UNCONNECTED[10:0]),
        .axis_dbiterr(NLW_U0_axis_dbiterr_UNCONNECTED),
        .axis_injectdbiterr(1'b0),
        .axis_injectsbiterr(1'b0),
        .axis_overflow(NLW_U0_axis_overflow_UNCONNECTED),
        .axis_prog_empty(NLW_U0_axis_prog_empty_UNCONNECTED),
        .axis_prog_empty_thresh({1'b0,1'b0,1'b0,1'b0,1'b0,1'b0,1'b0,1'b0,1'b0,1'b0}),
        .axis_prog_full(NLW_U0_axis_prog_full_UNCONNECTED),
        .axis_prog_full_thresh({1'b0,1'b0,1'b0,1'b0,1'b0,1'b0,1'b0,1'b0,1'b0,1'b0}),
        .axis_rd_data_count(NLW_U0_axis_rd_data_count_UNCONNECTED[10:0]),
        .axis_sbiterr(NLW_U0_axis_sbiterr_UNCONNECTED),
        .axis_underflow(NLW_U0_axis_underflow_UNCONNECTED),
        .axis_wr_data_count(NLW_U0_axis_wr_data_count_UNCONNECTED[10:0]),
        .backup(1'b0),
        .backup_marker(1'b0),
        .clk(1'b0),
        .data_count(NLW_U0_data_count_UNCONNECTED[7:0]),
        .dbiterr(NLW_U0_dbiterr_UNCONNECTED),
        .din(din),
        .dout(dout),
        .empty(empty),
        .full(full),
        .injectdbiterr(1'b0),
        .injectsbiterr(1'b0),
        .int_clk(1'b0),
        .m_aclk(1'b0),
        .m_aclk_en(1'b0),
        .m_axi_araddr(NLW_U0_m_axi_araddr_UNCONNECTED[31:0]),
        .m_axi_arburst(NLW_U0_m_axi_arburst_UNCONNECTED[1:0]),
        .m_axi_arcache(NLW_U0_m_axi_arcache_UNCONNECTED[3:0]),
        .m_axi_arid(NLW_U0_m_axi_arid_UNCONNECTED[0]),
        .m_axi_arlen(NLW_U0_m_axi_arlen_UNCONNECTED[7:0]),
        .m_axi_arlock(NLW_U0_m_axi_arlock_UNCONNECTED[0]),
        .m_axi_arprot(NLW_U0_m_axi_arprot_UNCONNECTED[2:0]),
        .m_axi_arqos(NLW_U0_m_axi_arqos_UNCONNECTED[3:0]),
        .m_axi_arready(1'b0),
        .m_axi_arregion(NLW_U0_m_axi_arregion_UNCONNECTED[3:0]),
        .m_axi_arsize(NLW_U0_m_axi_arsize_UNCONNECTED[2:0]),
        .m_axi_aruser(NLW_U0_m_axi_aruser_UNCONNECTED[0]),
        .m_axi_arvalid(NLW_U0_m_axi_arvalid_UNCONNECTED),
        .m_axi_awaddr(NLW_U0_m_axi_awaddr_UNCONNECTED[31:0]),
        .m_axi_awburst(NLW_U0_m_axi_awburst_UNCONNECTED[1:0]),
        .m_axi_awcache(NLW_U0_m_axi_awcache_UNCONNECTED[3:0]),
        .m_axi_awid(NLW_U0_m_axi_awid_UNCONNECTED[0]),
        .m_axi_awlen(NLW_U0_m_axi_awlen_UNCONNECTED[7:0]),
        .m_axi_awlock(NLW_U0_m_axi_awlock_UNCONNECTED[0]),
        .m_axi_awprot(NLW_U0_m_axi_awprot_UNCONNECTED[2:0]),
        .m_axi_awqos(NLW_U0_m_axi_awqos_UNCONNECTED[3:0]),
        .m_axi_awready(1'b0),
        .m_axi_awregion(NLW_U0_m_axi_awregion_UNCONNECTED[3:0]),
        .m_axi_awsize(NLW_U0_m_axi_awsize_UNCONNECTED[2:0]),
        .m_axi_awuser(NLW_U0_m_axi_awuser_UNCONNECTED[0]),
        .m_axi_awvalid(NLW_U0_m_axi_awvalid_UNCONNECTED),
        .m_axi_bid(1'b0),
        .m_axi_bready(NLW_U0_m_axi_bready_UNCONNECTED),
        .m_axi_bresp({1'b0,1'b0}),
        .m_axi_buser(1'b0),
        .m_axi_bvalid(1'b0),
        .m_axi_rdata({1'b0,1'b0,1'b0,1'b0,1'b0,1'b0,1'b0,1'b0,1'b0,1'b0,1'b0,1'b0,1'b0,1'b0,1'b0,1'b0,1'b0,1'b0,1'b0,1'b0,1'b0,1'b0,1'b0,1'b0,1'b0,1'b0,1'b0,1'b0,1'b0,1'b0,1'b0,1'b0,1'b0,1'b0,1'b0,1'b0,1'b0,1'b0,1'b0,1'b0,1'b0,1'b0,1'b0,1'b0,1'b0,1'b0,1'b0,1'b0,1'b0,1'b0,1'b0,1'b0,1'b0,1'b0,1'b0,1'b0,1'b0,1'b0,1'b0,1'b0,1'b0,1'b0,1'b0,1'b0}),
        .m_axi_rid(1'b0),
        .m_axi_rlast(1'b0),
        .m_axi_rready(NLW_U0_m_axi_rready_UNCONNECTED),
        .m_axi_rresp({1'b0,1'b0}),
        .m_axi_ruser(1'b0),
        .m_axi_rvalid(1'b0),
        .m_axi_wdata(NLW_U0_m_axi_wdata_UNCONNECTED[63:0]),
        .m_axi_wid(NLW_U0_m_axi_wid_UNCONNECTED[0]),
        .m_axi_wlast(NLW_U0_m_axi_wlast_UNCONNECTED),
        .m_axi_wready(1'b0),
        .m_axi_wstrb(NLW_U0_m_axi_wstrb_UNCONNECTED[7:0]),
        .m_axi_wuser(NLW_U0_m_axi_wuser_UNCONNECTED[0]),
        .m_axi_wvalid(NLW_U0_m_axi_wvalid_UNCONNECTED),
        .m_axis_tdata(NLW_U0_m_axis_tdata_UNCONNECTED[7:0]),
        .m_axis_tdest(NLW_U0_m_axis_tdest_UNCONNECTED[0]),
        .m_axis_tid(NLW_U0_m_axis_tid_UNCONNECTED[0]),
        .m_axis_tkeep(NLW_U0_m_axis_tkeep_UNCONNECTED[0]),
        .m_axis_tlast(NLW_U0_m_axis_tlast_UNCONNECTED),
        .m_axis_tready(1'b0),
        .m_axis_tstrb(NLW_U0_m_axis_tstrb_UNCONNECTED[0]),
        .m_axis_tuser(NLW_U0_m_axis_tuser_UNCONNECTED[3:0]),
        .m_axis_tvalid(NLW_U0_m_axis_tvalid_UNCONNECTED),
        .overflow(NLW_U0_overflow_UNCONNECTED),
        .prog_empty(NLW_U0_prog_empty_UNCONNECTED),
        .prog_empty_thresh({1'b0,1'b0,1'b0,1'b0,1'b0,1'b0,1'b0,1'b0}),
        .prog_empty_thresh_assert({1'b0,1'b0,1'b0,1'b0,1'b0,1'b0,1'b0,1'b0}),
        .prog_empty_thresh_negate({1'b0,1'b0,1'b0,1'b0,1'b0,1'b0,1'b0,1'b0}),
        .prog_full(NLW_U0_prog_full_UNCONNECTED),
        .prog_full_thresh({1'b0,1'b0,1'b0,1'b0,1'b0,1'b0,1'b0,1'b0}),
        .prog_full_thresh_assert({1'b0,1'b0,1'b0,1'b0,1'b0,1'b0,1'b0,1'b0}),
        .prog_full_thresh_negate({1'b0,1'b0,1'b0,1'b0,1'b0,1'b0,1'b0,1'b0}),
        .rd_clk(rd_clk),
        .rd_data_count(rd_data_count),
        .rd_en(rd_en),
        .rd_rst(1'b0),
        .rd_rst_busy(rd_rst_busy),
        .rst(rst),
        .s_aclk(1'b0),
        .s_aclk_en(1'b0),
        .s_aresetn(1'b0),
        .s_axi_araddr({1'b0,1'b0,1'b0,1'b0,1'b0,1'b0,1'b0,1'b0,1'b0,1'b0,1'b0,1'b0,1'b0,1'b0,1'b0,1'b0,1'b0,1'b0,1'b0,1'b0,1'b0,1'b0,1'b0,1'b0,1'b0,1'b0,1'b0,1'b0,1'b0,1'b0,1'b0,1'b0}),
        .s_axi_arburst({1'b0,1'b0}),
        .s_axi_arcache({1'b0,1'b0,1'b0,1'b0}),
        .s_axi_arid(1'b0),
        .s_axi_arlen({1'b0,1'b0,1'b0,1'b0,1'b0,1'b0,1'b0,1'b0}),
        .s_axi_arlock(1'b0),
        .s_axi_arprot({1'b0,1'b0,1'b0}),
        .s_axi_arqos({1'b0,1'b0,1'b0,1'b0}),
        .s_axi_arready(NLW_U0_s_axi_arready_UNCONNECTED),
        .s_axi_arregion({1'b0,1'b0,1'b0,1'b0}),
        .s_axi_arsize({1'b0,1'b0,1'b0}),
        .s_axi_aruser(1'b0),
        .s_axi_arvalid(1'b0),
        .s_axi_awaddr({1'b0,1'b0,1'b0,1'b0,1'b0,1'b0,1'b0,1'b0,1'b0,1'b0,1'b0,1'b0,1'b0,1'b0,1'b0,1'b0,1'b0,1'b0,1'b0,1'b0,1'b0,1'b0,1'b0,1'b0,1'b0,1'b0,1'b0,1'b0,1'b0,1'b0,1'b0,1'b0}),
        .s_axi_awburst({1'b0,1'b0}),
        .s_axi_awcache({1'b0,1'b0,1'b0,1'b0}),
        .s_axi_awid(1'b0),
        .s_axi_awlen({1'b0,1'b0,1'b0,1'b0,1'b0,1'b0,1'b0,1'b0}),
        .s_axi_awlock(1'b0),
        .s_axi_awprot({1'b0,1'b0,1'b0}),
        .s_axi_awqos({1'b0,1'b0,1'b0,1'b0}),
        .s_axi_awready(NLW_U0_s_axi_awready_UNCONNECTED),
        .s_axi_awregion({1'b0,1'b0,1'b0,1'b0}),
        .s_axi_awsize({1'b0,1'b0,1'b0}),
        .s_axi_awuser(1'b0),
        .s_axi_awvalid(1'b0),
        .s_axi_bid(NLW_U0_s_axi_bid_UNCONNECTED[0]),
        .s_axi_bready(1'b0),
        .s_axi_bresp(NLW_U0_s_axi_bresp_UNCONNECTED[1:0]),
        .s_axi_buser(NLW_U0_s_axi_buser_UNCONNECTED[0]),
        .s_axi_bvalid(NLW_U0_s_axi_bvalid_UNCONNECTED),
        .s_axi_rdata(NLW_U0_s_axi_rdata_UNCONNECTED[63:0]),
        .s_axi_rid(NLW_U0_s_axi_rid_UNCONNECTED[0]),
        .s_axi_rlast(NLW_U0_s_axi_rlast_UNCONNECTED),
        .s_axi_rready(1'b0),
        .s_axi_rresp(NLW_U0_s_axi_rresp_UNCONNECTED[1:0]),
        .s_axi_ruser(NLW_U0_s_axi_ruser_UNCONNECTED[0]),
        .s_axi_rvalid(NLW_U0_s_axi_rvalid_UNCONNECTED),
        .s_axi_wdata({1'b0,1'b0,1'b0,1'b0,1'b0,1'b0,1'b0,1'b0,1'b0,1'b0,1'b0,1'b0,1'b0,1'b0,1'b0,1'b0,1'b0,1'b0,1'b0,1'b0,1'b0,1'b0,1'b0,1'b0,1'b0,1'b0,1'b0,1'b0,1'b0,1'b0,1'b0,1'b0,1'b0,1'b0,1'b0,1'b0,1'b0,1'b0,1'b0,1'b0,1'b0,1'b0,1'b0,1'b0,1'b0,1'b0,1'b0,1'b0,1'b0,1'b0,1'b0,1'b0,1'b0,1'b0,1'b0,1'b0,1'b0,1'b0,1'b0,1'b0,1'b0,1'b0,1'b0,1'b0}),
        .s_axi_wid(1'b0),
        .s_axi_wlast(1'b0),
        .s_axi_wready(NLW_U0_s_axi_wready_UNCONNECTED),
        .s_axi_wstrb({1'b0,1'b0,1'b0,1'b0,1'b0,1'b0,1'b0,1'b0}),
        .s_axi_wuser(1'b0),
        .s_axi_wvalid(1'b0),
        .s_axis_tdata({1'b0,1'b0,1'b0,1'b0,1'b0,1'b0,1'b0,1'b0}),
        .s_axis_tdest(1'b0),
        .s_axis_tid(1'b0),
        .s_axis_tkeep(1'b0),
        .s_axis_tlast(1'b0),
        .s_axis_tready(NLW_U0_s_axis_tready_UNCONNECTED),
        .s_axis_tstrb(1'b0),
        .s_axis_tuser({1'b0,1'b0,1'b0,1'b0}),
        .s_axis_tvalid(1'b0),
        .sbiterr(NLW_U0_sbiterr_UNCONNECTED),
        .sleep(1'b0),
        .srst(1'b0),
        .underflow(NLW_U0_underflow_UNCONNECTED),
        .valid(NLW_U0_valid_UNCONNECTED),
        .wr_ack(NLW_U0_wr_ack_UNCONNECTED),
        .wr_clk(wr_clk),
        .wr_data_count(NLW_U0_wr_data_count_UNCONNECTED[7:0]),
        .wr_en(wr_en),
        .wr_rst(1'b0),
        .wr_rst_busy(wr_rst_busy));
endmodule

(* DEST_SYNC_FF = "2" *) (* INIT_SYNC_FF = "0" *) (* REG_OUTPUT = "1" *) 
(* SIM_ASSERT_CHK = "0" *) (* SIM_LOSSLESS_GRAY_CHK = "0" *) (* VERSION = "0" *) 
(* WIDTH = "8" *) (* XPM_MODULE = "TRUE" *) (* is_du_within_envelope = "true" *) 
(* keep_hierarchy = "true" *) (* xpm_cdc = "GRAY" *) 
module asg_dat_fifo_xpm_cdc_gray
   (src_clk,
    src_in_bin,
    dest_clk,
    dest_out_bin);
  input src_clk;
  input [7:0]src_in_bin;
  input dest_clk;
  output [7:0]dest_out_bin;

  wire [7:0]async_path;
  wire [6:0]binval;
  wire dest_clk;
  (* RTL_KEEP = "true" *) (* async_reg = "true" *) (* xpm_cdc = "GRAY" *) wire [7:0]\dest_graysync_ff[0] ;
  (* RTL_KEEP = "true" *) (* async_reg = "true" *) (* xpm_cdc = "GRAY" *) wire [7:0]\dest_graysync_ff[1] ;
  wire [7:0]dest_out_bin;
  wire [6:0]gray_enc;
  wire src_clk;
  wire [7:0]src_in_bin;

  (* ASYNC_REG *) 
  (* KEEP = "true" *) 
  (* XPM_CDC = "GRAY" *) 
  FDRE \dest_graysync_ff_reg[0][0] 
       (.C(dest_clk),
        .CE(1'b1),
        .D(async_path[0]),
        .Q(\dest_graysync_ff[0] [0]),
        .R(1'b0));
  (* ASYNC_REG *) 
  (* KEEP = "true" *) 
  (* XPM_CDC = "GRAY" *) 
  FDRE \dest_graysync_ff_reg[0][1] 
       (.C(dest_clk),
        .CE(1'b1),
        .D(async_path[1]),
        .Q(\dest_graysync_ff[0] [1]),
        .R(1'b0));
  (* ASYNC_REG *) 
  (* KEEP = "true" *) 
  (* XPM_CDC = "GRAY" *) 
  FDRE \dest_graysync_ff_reg[0][2] 
       (.C(dest_clk),
        .CE(1'b1),
        .D(async_path[2]),
        .Q(\dest_graysync_ff[0] [2]),
        .R(1'b0));
  (* ASYNC_REG *) 
  (* KEEP = "true" *) 
  (* XPM_CDC = "GRAY" *) 
  FDRE \dest_graysync_ff_reg[0][3] 
       (.C(dest_clk),
        .CE(1'b1),
        .D(async_path[3]),
        .Q(\dest_graysync_ff[0] [3]),
        .R(1'b0));
  (* ASYNC_REG *) 
  (* KEEP = "true" *) 
  (* XPM_CDC = "GRAY" *) 
  FDRE \dest_graysync_ff_reg[0][4] 
       (.C(dest_clk),
        .CE(1'b1),
        .D(async_path[4]),
        .Q(\dest_graysync_ff[0] [4]),
        .R(1'b0));
  (* ASYNC_REG *) 
  (* KEEP = "true" *) 
  (* XPM_CDC = "GRAY" *) 
  FDRE \dest_graysync_ff_reg[0][5] 
       (.C(dest_clk),
        .CE(1'b1),
        .D(async_path[5]),
        .Q(\dest_graysync_ff[0] [5]),
        .R(1'b0));
  (* ASYNC_REG *) 
  (* KEEP = "true" *) 
  (* XPM_CDC = "GRAY" *) 
  FDRE \dest_graysync_ff_reg[0][6] 
       (.C(dest_clk),
        .CE(1'b1),
        .D(async_path[6]),
        .Q(\dest_graysync_ff[0] [6]),
        .R(1'b0));
  (* ASYNC_REG *) 
  (* KEEP = "true" *) 
  (* XPM_CDC = "GRAY" *) 
  FDRE \dest_graysync_ff_reg[0][7] 
       (.C(dest_clk),
        .CE(1'b1),
        .D(async_path[7]),
        .Q(\dest_graysync_ff[0] [7]),
        .R(1'b0));
  (* ASYNC_REG *) 
  (* KEEP = "true" *) 
  (* XPM_CDC = "GRAY" *) 
  FDRE \dest_graysync_ff_reg[1][0] 
       (.C(dest_clk),
        .CE(1'b1),
        .D(\dest_graysync_ff[0] [0]),
        .Q(\dest_graysync_ff[1] [0]),
        .R(1'b0));
  (* ASYNC_REG *) 
  (* KEEP = "true" *) 
  (* XPM_CDC = "GRAY" *) 
  FDRE \dest_graysync_ff_reg[1][1] 
       (.C(dest_clk),
        .CE(1'b1),
        .D(\dest_graysync_ff[0] [1]),
        .Q(\dest_graysync_ff[1] [1]),
        .R(1'b0));
  (* ASYNC_REG *) 
  (* KEEP = "true" *) 
  (* XPM_CDC = "GRAY" *) 
  FDRE \dest_graysync_ff_reg[1][2] 
       (.C(dest_clk),
        .CE(1'b1),
        .D(\dest_graysync_ff[0] [2]),
        .Q(\dest_graysync_ff[1] [2]),
        .R(1'b0));
  (* ASYNC_REG *) 
  (* KEEP = "true" *) 
  (* XPM_CDC = "GRAY" *) 
  FDRE \dest_graysync_ff_reg[1][3] 
       (.C(dest_clk),
        .CE(1'b1),
        .D(\dest_graysync_ff[0] [3]),
        .Q(\dest_graysync_ff[1] [3]),
        .R(1'b0));
  (* ASYNC_REG *) 
  (* KEEP = "true" *) 
  (* XPM_CDC = "GRAY" *) 
  FDRE \dest_graysync_ff_reg[1][4] 
       (.C(dest_clk),
        .CE(1'b1),
        .D(\dest_graysync_ff[0] [4]),
        .Q(\dest_graysync_ff[1] [4]),
        .R(1'b0));
  (* ASYNC_REG *) 
  (* KEEP = "true" *) 
  (* XPM_CDC = "GRAY" *) 
  FDRE \dest_graysync_ff_reg[1][5] 
       (.C(dest_clk),
        .CE(1'b1),
        .D(\dest_graysync_ff[0] [5]),
        .Q(\dest_graysync_ff[1] [5]),
        .R(1'b0));
  (* ASYNC_REG *) 
  (* KEEP = "true" *) 
  (* XPM_CDC = "GRAY" *) 
  FDRE \dest_graysync_ff_reg[1][6] 
       (.C(dest_clk),
        .CE(1'b1),
        .D(\dest_graysync_ff[0] [6]),
        .Q(\dest_graysync_ff[1] [6]),
        .R(1'b0));
  (* ASYNC_REG *) 
  (* KEEP = "true" *) 
  (* XPM_CDC = "GRAY" *) 
  FDRE \dest_graysync_ff_reg[1][7] 
       (.C(dest_clk),
        .CE(1'b1),
        .D(\dest_graysync_ff[0] [7]),
        .Q(\dest_graysync_ff[1] [7]),
        .R(1'b0));
  LUT3 #(
    .INIT(8'h96)) 
    \dest_out_bin_ff[0]_i_1 
       (.I0(\dest_graysync_ff[1] [0]),
        .I1(binval[2]),
        .I2(\dest_graysync_ff[1] [1]),
        .O(binval[0]));
  LUT2 #(
    .INIT(4'h6)) 
    \dest_out_bin_ff[1]_i_1 
       (.I0(\dest_graysync_ff[1] [1]),
        .I1(binval[2]),
        .O(binval[1]));
  LUT6 #(
    .INIT(64'h6996966996696996)) 
    \dest_out_bin_ff[2]_i_1 
       (.I0(\dest_graysync_ff[1] [2]),
        .I1(\dest_graysync_ff[1] [4]),
        .I2(\dest_graysync_ff[1] [6]),
        .I3(\dest_graysync_ff[1] [7]),
        .I4(\dest_graysync_ff[1] [5]),
        .I5(\dest_graysync_ff[1] [3]),
        .O(binval[2]));
  LUT5 #(
    .INIT(32'h96696996)) 
    \dest_out_bin_ff[3]_i_1 
       (.I0(\dest_graysync_ff[1] [3]),
        .I1(\dest_graysync_ff[1] [5]),
        .I2(\dest_graysync_ff[1] [7]),
        .I3(\dest_graysync_ff[1] [6]),
        .I4(\dest_graysync_ff[1] [4]),
        .O(binval[3]));
  LUT4 #(
    .INIT(16'h6996)) 
    \dest_out_bin_ff[4]_i_1 
       (.I0(\dest_graysync_ff[1] [4]),
        .I1(\dest_graysync_ff[1] [6]),
        .I2(\dest_graysync_ff[1] [7]),
        .I3(\dest_graysync_ff[1] [5]),
        .O(binval[4]));
  LUT3 #(
    .INIT(8'h96)) 
    \dest_out_bin_ff[5]_i_1 
       (.I0(\dest_graysync_ff[1] [5]),
        .I1(\dest_graysync_ff[1] [7]),
        .I2(\dest_graysync_ff[1] [6]),
        .O(binval[5]));
  LUT2 #(
    .INIT(4'h6)) 
    \dest_out_bin_ff[6]_i_1 
       (.I0(\dest_graysync_ff[1] [6]),
        .I1(\dest_graysync_ff[1] [7]),
        .O(binval[6]));
  FDRE \dest_out_bin_ff_reg[0] 
       (.C(dest_clk),
        .CE(1'b1),
        .D(binval[0]),
        .Q(dest_out_bin[0]),
        .R(1'b0));
  FDRE \dest_out_bin_ff_reg[1] 
       (.C(dest_clk),
        .CE(1'b1),
        .D(binval[1]),
        .Q(dest_out_bin[1]),
        .R(1'b0));
  FDRE \dest_out_bin_ff_reg[2] 
       (.C(dest_clk),
        .CE(1'b1),
        .D(binval[2]),
        .Q(dest_out_bin[2]),
        .R(1'b0));
  FDRE \dest_out_bin_ff_reg[3] 
       (.C(dest_clk),
        .CE(1'b1),
        .D(binval[3]),
        .Q(dest_out_bin[3]),
        .R(1'b0));
  FDRE \dest_out_bin_ff_reg[4] 
       (.C(dest_clk),
        .CE(1'b1),
        .D(binval[4]),
        .Q(dest_out_bin[4]),
        .R(1'b0));
  FDRE \dest_out_bin_ff_reg[5] 
       (.C(dest_clk),
        .CE(1'b1),
        .D(binval[5]),
        .Q(dest_out_bin[5]),
        .R(1'b0));
  FDRE \dest_out_bin_ff_reg[6] 
       (.C(dest_clk),
        .CE(1'b1),
        .D(binval[6]),
        .Q(dest_out_bin[6]),
        .R(1'b0));
  FDRE \dest_out_bin_ff_reg[7] 
       (.C(dest_clk),
        .CE(1'b1),
        .D(\dest_graysync_ff[1] [7]),
        .Q(dest_out_bin[7]),
        .R(1'b0));
  (* SOFT_HLUTNM = "soft_lutpair3" *) 
  LUT2 #(
    .INIT(4'h6)) 
    \src_gray_ff[0]_i_1 
       (.I0(src_in_bin[1]),
        .I1(src_in_bin[0]),
        .O(gray_enc[0]));
  (* SOFT_HLUTNM = "soft_lutpair3" *) 
  LUT2 #(
    .INIT(4'h6)) 
    \src_gray_ff[1]_i_1 
       (.I0(src_in_bin[2]),
        .I1(src_in_bin[1]),
        .O(gray_enc[1]));
  (* SOFT_HLUTNM = "soft_lutpair4" *) 
  LUT2 #(
    .INIT(4'h6)) 
    \src_gray_ff[2]_i_1 
       (.I0(src_in_bin[3]),
        .I1(src_in_bin[2]),
        .O(gray_enc[2]));
  (* SOFT_HLUTNM = "soft_lutpair4" *) 
  LUT2 #(
    .INIT(4'h6)) 
    \src_gray_ff[3]_i_1 
       (.I0(src_in_bin[4]),
        .I1(src_in_bin[3]),
        .O(gray_enc[3]));
  (* SOFT_HLUTNM = "soft_lutpair5" *) 
  LUT2 #(
    .INIT(4'h6)) 
    \src_gray_ff[4]_i_1 
       (.I0(src_in_bin[5]),
        .I1(src_in_bin[4]),
        .O(gray_enc[4]));
  (* SOFT_HLUTNM = "soft_lutpair5" *) 
  LUT2 #(
    .INIT(4'h6)) 
    \src_gray_ff[5]_i_1 
       (.I0(src_in_bin[6]),
        .I1(src_in_bin[5]),
        .O(gray_enc[5]));
  LUT2 #(
    .INIT(4'h6)) 
    \src_gray_ff[6]_i_1 
       (.I0(src_in_bin[7]),
        .I1(src_in_bin[6]),
        .O(gray_enc[6]));
  FDRE \src_gray_ff_reg[0] 
       (.C(src_clk),
        .CE(1'b1),
        .D(gray_enc[0]),
        .Q(async_path[0]),
        .R(1'b0));
  FDRE \src_gray_ff_reg[1] 
       (.C(src_clk),
        .CE(1'b1),
        .D(gray_enc[1]),
        .Q(async_path[1]),
        .R(1'b0));
  FDRE \src_gray_ff_reg[2] 
       (.C(src_clk),
        .CE(1'b1),
        .D(gray_enc[2]),
        .Q(async_path[2]),
        .R(1'b0));
  FDRE \src_gray_ff_reg[3] 
       (.C(src_clk),
        .CE(1'b1),
        .D(gray_enc[3]),
        .Q(async_path[3]),
        .R(1'b0));
  FDRE \src_gray_ff_reg[4] 
       (.C(src_clk),
        .CE(1'b1),
        .D(gray_enc[4]),
        .Q(async_path[4]),
        .R(1'b0));
  FDRE \src_gray_ff_reg[5] 
       (.C(src_clk),
        .CE(1'b1),
        .D(gray_enc[5]),
        .Q(async_path[5]),
        .R(1'b0));
  FDRE \src_gray_ff_reg[6] 
       (.C(src_clk),
        .CE(1'b1),
        .D(gray_enc[6]),
        .Q(async_path[6]),
        .R(1'b0));
  FDRE \src_gray_ff_reg[7] 
       (.C(src_clk),
        .CE(1'b1),
        .D(src_in_bin[7]),
        .Q(async_path[7]),
        .R(1'b0));
endmodule

(* DEST_SYNC_FF = "2" *) (* INIT_SYNC_FF = "0" *) (* ORIG_REF_NAME = "xpm_cdc_gray" *) 
(* REG_OUTPUT = "1" *) (* SIM_ASSERT_CHK = "0" *) (* SIM_LOSSLESS_GRAY_CHK = "0" *) 
(* VERSION = "0" *) (* WIDTH = "8" *) (* XPM_MODULE = "TRUE" *) 
(* is_du_within_envelope = "true" *) (* keep_hierarchy = "true" *) (* xpm_cdc = "GRAY" *) 
module asg_dat_fifo_xpm_cdc_gray__2
   (src_clk,
    src_in_bin,
    dest_clk,
    dest_out_bin);
  input src_clk;
  input [7:0]src_in_bin;
  input dest_clk;
  output [7:0]dest_out_bin;

  wire [7:0]async_path;
  wire [6:0]binval;
  wire dest_clk;
  (* RTL_KEEP = "true" *) (* async_reg = "true" *) (* xpm_cdc = "GRAY" *) wire [7:0]\dest_graysync_ff[0] ;
  (* RTL_KEEP = "true" *) (* async_reg = "true" *) (* xpm_cdc = "GRAY" *) wire [7:0]\dest_graysync_ff[1] ;
  wire [7:0]dest_out_bin;
  wire [6:0]gray_enc;
  wire src_clk;
  wire [7:0]src_in_bin;

  (* ASYNC_REG *) 
  (* KEEP = "true" *) 
  (* XPM_CDC = "GRAY" *) 
  FDRE \dest_graysync_ff_reg[0][0] 
       (.C(dest_clk),
        .CE(1'b1),
        .D(async_path[0]),
        .Q(\dest_graysync_ff[0] [0]),
        .R(1'b0));
  (* ASYNC_REG *) 
  (* KEEP = "true" *) 
  (* XPM_CDC = "GRAY" *) 
  FDRE \dest_graysync_ff_reg[0][1] 
       (.C(dest_clk),
        .CE(1'b1),
        .D(async_path[1]),
        .Q(\dest_graysync_ff[0] [1]),
        .R(1'b0));
  (* ASYNC_REG *) 
  (* KEEP = "true" *) 
  (* XPM_CDC = "GRAY" *) 
  FDRE \dest_graysync_ff_reg[0][2] 
       (.C(dest_clk),
        .CE(1'b1),
        .D(async_path[2]),
        .Q(\dest_graysync_ff[0] [2]),
        .R(1'b0));
  (* ASYNC_REG *) 
  (* KEEP = "true" *) 
  (* XPM_CDC = "GRAY" *) 
  FDRE \dest_graysync_ff_reg[0][3] 
       (.C(dest_clk),
        .CE(1'b1),
        .D(async_path[3]),
        .Q(\dest_graysync_ff[0] [3]),
        .R(1'b0));
  (* ASYNC_REG *) 
  (* KEEP = "true" *) 
  (* XPM_CDC = "GRAY" *) 
  FDRE \dest_graysync_ff_reg[0][4] 
       (.C(dest_clk),
        .CE(1'b1),
        .D(async_path[4]),
        .Q(\dest_graysync_ff[0] [4]),
        .R(1'b0));
  (* ASYNC_REG *) 
  (* KEEP = "true" *) 
  (* XPM_CDC = "GRAY" *) 
  FDRE \dest_graysync_ff_reg[0][5] 
       (.C(dest_clk),
        .CE(1'b1),
        .D(async_path[5]),
        .Q(\dest_graysync_ff[0] [5]),
        .R(1'b0));
  (* ASYNC_REG *) 
  (* KEEP = "true" *) 
  (* XPM_CDC = "GRAY" *) 
  FDRE \dest_graysync_ff_reg[0][6] 
       (.C(dest_clk),
        .CE(1'b1),
        .D(async_path[6]),
        .Q(\dest_graysync_ff[0] [6]),
        .R(1'b0));
  (* ASYNC_REG *) 
  (* KEEP = "true" *) 
  (* XPM_CDC = "GRAY" *) 
  FDRE \dest_graysync_ff_reg[0][7] 
       (.C(dest_clk),
        .CE(1'b1),
        .D(async_path[7]),
        .Q(\dest_graysync_ff[0] [7]),
        .R(1'b0));
  (* ASYNC_REG *) 
  (* KEEP = "true" *) 
  (* XPM_CDC = "GRAY" *) 
  FDRE \dest_graysync_ff_reg[1][0] 
       (.C(dest_clk),
        .CE(1'b1),
        .D(\dest_graysync_ff[0] [0]),
        .Q(\dest_graysync_ff[1] [0]),
        .R(1'b0));
  (* ASYNC_REG *) 
  (* KEEP = "true" *) 
  (* XPM_CDC = "GRAY" *) 
  FDRE \dest_graysync_ff_reg[1][1] 
       (.C(dest_clk),
        .CE(1'b1),
        .D(\dest_graysync_ff[0] [1]),
        .Q(\dest_graysync_ff[1] [1]),
        .R(1'b0));
  (* ASYNC_REG *) 
  (* KEEP = "true" *) 
  (* XPM_CDC = "GRAY" *) 
  FDRE \dest_graysync_ff_reg[1][2] 
       (.C(dest_clk),
        .CE(1'b1),
        .D(\dest_graysync_ff[0] [2]),
        .Q(\dest_graysync_ff[1] [2]),
        .R(1'b0));
  (* ASYNC_REG *) 
  (* KEEP = "true" *) 
  (* XPM_CDC = "GRAY" *) 
  FDRE \dest_graysync_ff_reg[1][3] 
       (.C(dest_clk),
        .CE(1'b1),
        .D(\dest_graysync_ff[0] [3]),
        .Q(\dest_graysync_ff[1] [3]),
        .R(1'b0));
  (* ASYNC_REG *) 
  (* KEEP = "true" *) 
  (* XPM_CDC = "GRAY" *) 
  FDRE \dest_graysync_ff_reg[1][4] 
       (.C(dest_clk),
        .CE(1'b1),
        .D(\dest_graysync_ff[0] [4]),
        .Q(\dest_graysync_ff[1] [4]),
        .R(1'b0));
  (* ASYNC_REG *) 
  (* KEEP = "true" *) 
  (* XPM_CDC = "GRAY" *) 
  FDRE \dest_graysync_ff_reg[1][5] 
       (.C(dest_clk),
        .CE(1'b1),
        .D(\dest_graysync_ff[0] [5]),
        .Q(\dest_graysync_ff[1] [5]),
        .R(1'b0));
  (* ASYNC_REG *) 
  (* KEEP = "true" *) 
  (* XPM_CDC = "GRAY" *) 
  FDRE \dest_graysync_ff_reg[1][6] 
       (.C(dest_clk),
        .CE(1'b1),
        .D(\dest_graysync_ff[0] [6]),
        .Q(\dest_graysync_ff[1] [6]),
        .R(1'b0));
  (* ASYNC_REG *) 
  (* KEEP = "true" *) 
  (* XPM_CDC = "GRAY" *) 
  FDRE \dest_graysync_ff_reg[1][7] 
       (.C(dest_clk),
        .CE(1'b1),
        .D(\dest_graysync_ff[0] [7]),
        .Q(\dest_graysync_ff[1] [7]),
        .R(1'b0));
  LUT3 #(
    .INIT(8'h96)) 
    \dest_out_bin_ff[0]_i_1 
       (.I0(\dest_graysync_ff[1] [0]),
        .I1(binval[2]),
        .I2(\dest_graysync_ff[1] [1]),
        .O(binval[0]));
  LUT2 #(
    .INIT(4'h6)) 
    \dest_out_bin_ff[1]_i_1 
       (.I0(\dest_graysync_ff[1] [1]),
        .I1(binval[2]),
        .O(binval[1]));
  LUT6 #(
    .INIT(64'h6996966996696996)) 
    \dest_out_bin_ff[2]_i_1 
       (.I0(\dest_graysync_ff[1] [2]),
        .I1(\dest_graysync_ff[1] [4]),
        .I2(\dest_graysync_ff[1] [6]),
        .I3(\dest_graysync_ff[1] [7]),
        .I4(\dest_graysync_ff[1] [5]),
        .I5(\dest_graysync_ff[1] [3]),
        .O(binval[2]));
  LUT5 #(
    .INIT(32'h96696996)) 
    \dest_out_bin_ff[3]_i_1 
       (.I0(\dest_graysync_ff[1] [3]),
        .I1(\dest_graysync_ff[1] [5]),
        .I2(\dest_graysync_ff[1] [7]),
        .I3(\dest_graysync_ff[1] [6]),
        .I4(\dest_graysync_ff[1] [4]),
        .O(binval[3]));
  LUT4 #(
    .INIT(16'h6996)) 
    \dest_out_bin_ff[4]_i_1 
       (.I0(\dest_graysync_ff[1] [4]),
        .I1(\dest_graysync_ff[1] [6]),
        .I2(\dest_graysync_ff[1] [7]),
        .I3(\dest_graysync_ff[1] [5]),
        .O(binval[4]));
  LUT3 #(
    .INIT(8'h96)) 
    \dest_out_bin_ff[5]_i_1 
       (.I0(\dest_graysync_ff[1] [5]),
        .I1(\dest_graysync_ff[1] [7]),
        .I2(\dest_graysync_ff[1] [6]),
        .O(binval[5]));
  LUT2 #(
    .INIT(4'h6)) 
    \dest_out_bin_ff[6]_i_1 
       (.I0(\dest_graysync_ff[1] [6]),
        .I1(\dest_graysync_ff[1] [7]),
        .O(binval[6]));
  FDRE \dest_out_bin_ff_reg[0] 
       (.C(dest_clk),
        .CE(1'b1),
        .D(binval[0]),
        .Q(dest_out_bin[0]),
        .R(1'b0));
  FDRE \dest_out_bin_ff_reg[1] 
       (.C(dest_clk),
        .CE(1'b1),
        .D(binval[1]),
        .Q(dest_out_bin[1]),
        .R(1'b0));
  FDRE \dest_out_bin_ff_reg[2] 
       (.C(dest_clk),
        .CE(1'b1),
        .D(binval[2]),
        .Q(dest_out_bin[2]),
        .R(1'b0));
  FDRE \dest_out_bin_ff_reg[3] 
       (.C(dest_clk),
        .CE(1'b1),
        .D(binval[3]),
        .Q(dest_out_bin[3]),
        .R(1'b0));
  FDRE \dest_out_bin_ff_reg[4] 
       (.C(dest_clk),
        .CE(1'b1),
        .D(binval[4]),
        .Q(dest_out_bin[4]),
        .R(1'b0));
  FDRE \dest_out_bin_ff_reg[5] 
       (.C(dest_clk),
        .CE(1'b1),
        .D(binval[5]),
        .Q(dest_out_bin[5]),
        .R(1'b0));
  FDRE \dest_out_bin_ff_reg[6] 
       (.C(dest_clk),
        .CE(1'b1),
        .D(binval[6]),
        .Q(dest_out_bin[6]),
        .R(1'b0));
  FDRE \dest_out_bin_ff_reg[7] 
       (.C(dest_clk),
        .CE(1'b1),
        .D(\dest_graysync_ff[1] [7]),
        .Q(dest_out_bin[7]),
        .R(1'b0));
  (* SOFT_HLUTNM = "soft_lutpair0" *) 
  LUT2 #(
    .INIT(4'h6)) 
    \src_gray_ff[0]_i_1 
       (.I0(src_in_bin[1]),
        .I1(src_in_bin[0]),
        .O(gray_enc[0]));
  (* SOFT_HLUTNM = "soft_lutpair0" *) 
  LUT2 #(
    .INIT(4'h6)) 
    \src_gray_ff[1]_i_1 
       (.I0(src_in_bin[2]),
        .I1(src_in_bin[1]),
        .O(gray_enc[1]));
  (* SOFT_HLUTNM = "soft_lutpair1" *) 
  LUT2 #(
    .INIT(4'h6)) 
    \src_gray_ff[2]_i_1 
       (.I0(src_in_bin[3]),
        .I1(src_in_bin[2]),
        .O(gray_enc[2]));
  (* SOFT_HLUTNM = "soft_lutpair1" *) 
  LUT2 #(
    .INIT(4'h6)) 
    \src_gray_ff[3]_i_1 
       (.I0(src_in_bin[4]),
        .I1(src_in_bin[3]),
        .O(gray_enc[3]));
  (* SOFT_HLUTNM = "soft_lutpair2" *) 
  LUT2 #(
    .INIT(4'h6)) 
    \src_gray_ff[4]_i_1 
       (.I0(src_in_bin[5]),
        .I1(src_in_bin[4]),
        .O(gray_enc[4]));
  (* SOFT_HLUTNM = "soft_lutpair2" *) 
  LUT2 #(
    .INIT(4'h6)) 
    \src_gray_ff[5]_i_1 
       (.I0(src_in_bin[6]),
        .I1(src_in_bin[5]),
        .O(gray_enc[5]));
  LUT2 #(
    .INIT(4'h6)) 
    \src_gray_ff[6]_i_1 
       (.I0(src_in_bin[7]),
        .I1(src_in_bin[6]),
        .O(gray_enc[6]));
  FDRE \src_gray_ff_reg[0] 
       (.C(src_clk),
        .CE(1'b1),
        .D(gray_enc[0]),
        .Q(async_path[0]),
        .R(1'b0));
  FDRE \src_gray_ff_reg[1] 
       (.C(src_clk),
        .CE(1'b1),
        .D(gray_enc[1]),
        .Q(async_path[1]),
        .R(1'b0));
  FDRE \src_gray_ff_reg[2] 
       (.C(src_clk),
        .CE(1'b1),
        .D(gray_enc[2]),
        .Q(async_path[2]),
        .R(1'b0));
  FDRE \src_gray_ff_reg[3] 
       (.C(src_clk),
        .CE(1'b1),
        .D(gray_enc[3]),
        .Q(async_path[3]),
        .R(1'b0));
  FDRE \src_gray_ff_reg[4] 
       (.C(src_clk),
        .CE(1'b1),
        .D(gray_enc[4]),
        .Q(async_path[4]),
        .R(1'b0));
  FDRE \src_gray_ff_reg[5] 
       (.C(src_clk),
        .CE(1'b1),
        .D(gray_enc[5]),
        .Q(async_path[5]),
        .R(1'b0));
  FDRE \src_gray_ff_reg[6] 
       (.C(src_clk),
        .CE(1'b1),
        .D(gray_enc[6]),
        .Q(async_path[6]),
        .R(1'b0));
  FDRE \src_gray_ff_reg[7] 
       (.C(src_clk),
        .CE(1'b1),
        .D(src_in_bin[7]),
        .Q(async_path[7]),
        .R(1'b0));
endmodule

(* DEST_SYNC_FF = "5" *) (* INIT_SYNC_FF = "0" *) (* SIM_ASSERT_CHK = "0" *) 
(* SRC_INPUT_REG = "0" *) (* VERSION = "0" *) (* XPM_MODULE = "TRUE" *) 
(* is_du_within_envelope = "true" *) (* keep_hierarchy = "true" *) (* xpm_cdc = "SINGLE" *) 
module asg_dat_fifo_xpm_cdc_single
   (src_clk,
    src_in,
    dest_clk,
    dest_out);
  input src_clk;
  input src_in;
  input dest_clk;
  output dest_out;

  wire dest_clk;
  wire src_in;
  (* RTL_KEEP = "true" *) (* async_reg = "true" *) (* xpm_cdc = "SINGLE" *) wire [4:0]syncstages_ff;

  assign dest_out = syncstages_ff[4];
  (* ASYNC_REG *) 
  (* KEEP = "true" *) 
  (* XPM_CDC = "SINGLE" *) 
  FDRE \syncstages_ff_reg[0] 
       (.C(dest_clk),
        .CE(1'b1),
        .D(src_in),
        .Q(syncstages_ff[0]),
        .R(1'b0));
  (* ASYNC_REG *) 
  (* KEEP = "true" *) 
  (* XPM_CDC = "SINGLE" *) 
  FDRE \syncstages_ff_reg[1] 
       (.C(dest_clk),
        .CE(1'b1),
        .D(syncstages_ff[0]),
        .Q(syncstages_ff[1]),
        .R(1'b0));
  (* ASYNC_REG *) 
  (* KEEP = "true" *) 
  (* XPM_CDC = "SINGLE" *) 
  FDRE \syncstages_ff_reg[2] 
       (.C(dest_clk),
        .CE(1'b1),
        .D(syncstages_ff[1]),
        .Q(syncstages_ff[2]),
        .R(1'b0));
  (* ASYNC_REG *) 
  (* KEEP = "true" *) 
  (* XPM_CDC = "SINGLE" *) 
  FDRE \syncstages_ff_reg[3] 
       (.C(dest_clk),
        .CE(1'b1),
        .D(syncstages_ff[2]),
        .Q(syncstages_ff[3]),
        .R(1'b0));
  (* ASYNC_REG *) 
  (* KEEP = "true" *) 
  (* XPM_CDC = "SINGLE" *) 
  FDRE \syncstages_ff_reg[4] 
       (.C(dest_clk),
        .CE(1'b1),
        .D(syncstages_ff[3]),
        .Q(syncstages_ff[4]),
        .R(1'b0));
endmodule

(* DEST_SYNC_FF = "5" *) (* INIT_SYNC_FF = "0" *) (* ORIG_REF_NAME = "xpm_cdc_single" *) 
(* SIM_ASSERT_CHK = "0" *) (* SRC_INPUT_REG = "0" *) (* VERSION = "0" *) 
(* XPM_MODULE = "TRUE" *) (* is_du_within_envelope = "true" *) (* keep_hierarchy = "true" *) 
(* xpm_cdc = "SINGLE" *) 
module asg_dat_fifo_xpm_cdc_single__2
   (src_clk,
    src_in,
    dest_clk,
    dest_out);
  input src_clk;
  input src_in;
  input dest_clk;
  output dest_out;

  wire dest_clk;
  wire src_in;
  (* RTL_KEEP = "true" *) (* async_reg = "true" *) (* xpm_cdc = "SINGLE" *) wire [4:0]syncstages_ff;

  assign dest_out = syncstages_ff[4];
  (* ASYNC_REG *) 
  (* KEEP = "true" *) 
  (* XPM_CDC = "SINGLE" *) 
  FDRE \syncstages_ff_reg[0] 
       (.C(dest_clk),
        .CE(1'b1),
        .D(src_in),
        .Q(syncstages_ff[0]),
        .R(1'b0));
  (* ASYNC_REG *) 
  (* KEEP = "true" *) 
  (* XPM_CDC = "SINGLE" *) 
  FDRE \syncstages_ff_reg[1] 
       (.C(dest_clk),
        .CE(1'b1),
        .D(syncstages_ff[0]),
        .Q(syncstages_ff[1]),
        .R(1'b0));
  (* ASYNC_REG *) 
  (* KEEP = "true" *) 
  (* XPM_CDC = "SINGLE" *) 
  FDRE \syncstages_ff_reg[2] 
       (.C(dest_clk),
        .CE(1'b1),
        .D(syncstages_ff[1]),
        .Q(syncstages_ff[2]),
        .R(1'b0));
  (* ASYNC_REG *) 
  (* KEEP = "true" *) 
  (* XPM_CDC = "SINGLE" *) 
  FDRE \syncstages_ff_reg[3] 
       (.C(dest_clk),
        .CE(1'b1),
        .D(syncstages_ff[2]),
        .Q(syncstages_ff[3]),
        .R(1'b0));
  (* ASYNC_REG *) 
  (* KEEP = "true" *) 
  (* XPM_CDC = "SINGLE" *) 
  FDRE \syncstages_ff_reg[4] 
       (.C(dest_clk),
        .CE(1'b1),
        .D(syncstages_ff[3]),
        .Q(syncstages_ff[4]),
        .R(1'b0));
endmodule

(* DEF_VAL = "1'b1" *) (* DEST_SYNC_FF = "5" *) (* INIT = "1" *) 
(* INIT_SYNC_FF = "0" *) (* SIM_ASSERT_CHK = "0" *) (* VERSION = "0" *) 
(* XPM_MODULE = "TRUE" *) (* is_du_within_envelope = "true" *) (* keep_hierarchy = "true" *) 
(* xpm_cdc = "SYNC_RST" *) 
module asg_dat_fifo_xpm_cdc_sync_rst
   (src_rst,
    dest_clk,
    dest_rst);
  input src_rst;
  input dest_clk;
  output dest_rst;

  wire dest_clk;
  wire src_rst;
  (* RTL_KEEP = "true" *) (* async_reg = "true" *) (* xpm_cdc = "SYNC_RST" *) wire [4:0]syncstages_ff;

  assign dest_rst = syncstages_ff[4];
  (* ASYNC_REG *) 
  (* KEEP = "true" *) 
  (* XPM_CDC = "SYNC_RST" *) 
  FDRE #(
    .INIT(1'b1)) 
    \syncstages_ff_reg[0] 
       (.C(dest_clk),
        .CE(1'b1),
        .D(src_rst),
        .Q(syncstages_ff[0]),
        .R(1'b0));
  (* ASYNC_REG *) 
  (* KEEP = "true" *) 
  (* XPM_CDC = "SYNC_RST" *) 
  FDRE #(
    .INIT(1'b1)) 
    \syncstages_ff_reg[1] 
       (.C(dest_clk),
        .CE(1'b1),
        .D(syncstages_ff[0]),
        .Q(syncstages_ff[1]),
        .R(1'b0));
  (* ASYNC_REG *) 
  (* KEEP = "true" *) 
  (* XPM_CDC = "SYNC_RST" *) 
  FDRE #(
    .INIT(1'b1)) 
    \syncstages_ff_reg[2] 
       (.C(dest_clk),
        .CE(1'b1),
        .D(syncstages_ff[1]),
        .Q(syncstages_ff[2]),
        .R(1'b0));
  (* ASYNC_REG *) 
  (* KEEP = "true" *) 
  (* XPM_CDC = "SYNC_RST" *) 
  FDRE #(
    .INIT(1'b1)) 
    \syncstages_ff_reg[3] 
       (.C(dest_clk),
        .CE(1'b1),
        .D(syncstages_ff[2]),
        .Q(syncstages_ff[3]),
        .R(1'b0));
  (* ASYNC_REG *) 
  (* KEEP = "true" *) 
  (* XPM_CDC = "SYNC_RST" *) 
  FDRE #(
    .INIT(1'b1)) 
    \syncstages_ff_reg[4] 
       (.C(dest_clk),
        .CE(1'b1),
        .D(syncstages_ff[3]),
        .Q(syncstages_ff[4]),
        .R(1'b0));
endmodule

(* DEF_VAL = "1'b1" *) (* DEST_SYNC_FF = "5" *) (* INIT = "1" *) 
(* INIT_SYNC_FF = "0" *) (* ORIG_REF_NAME = "xpm_cdc_sync_rst" *) (* SIM_ASSERT_CHK = "0" *) 
(* VERSION = "0" *) (* XPM_MODULE = "TRUE" *) (* is_du_within_envelope = "true" *) 
(* keep_hierarchy = "true" *) (* xpm_cdc = "SYNC_RST" *) 
module asg_dat_fifo_xpm_cdc_sync_rst__2
   (src_rst,
    dest_clk,
    dest_rst);
  input src_rst;
  input dest_clk;
  output dest_rst;

  wire dest_clk;
  wire src_rst;
  (* RTL_KEEP = "true" *) (* async_reg = "true" *) (* xpm_cdc = "SYNC_RST" *) wire [4:0]syncstages_ff;

  assign dest_rst = syncstages_ff[4];
  (* ASYNC_REG *) 
  (* KEEP = "true" *) 
  (* XPM_CDC = "SYNC_RST" *) 
  FDRE #(
    .INIT(1'b1)) 
    \syncstages_ff_reg[0] 
       (.C(dest_clk),
        .CE(1'b1),
        .D(src_rst),
        .Q(syncstages_ff[0]),
        .R(1'b0));
  (* ASYNC_REG *) 
  (* KEEP = "true" *) 
  (* XPM_CDC = "SYNC_RST" *) 
  FDRE #(
    .INIT(1'b1)) 
    \syncstages_ff_reg[1] 
       (.C(dest_clk),
        .CE(1'b1),
        .D(syncstages_ff[0]),
        .Q(syncstages_ff[1]),
        .R(1'b0));
  (* ASYNC_REG *) 
  (* KEEP = "true" *) 
  (* XPM_CDC = "SYNC_RST" *) 
  FDRE #(
    .INIT(1'b1)) 
    \syncstages_ff_reg[2] 
       (.C(dest_clk),
        .CE(1'b1),
        .D(syncstages_ff[1]),
        .Q(syncstages_ff[2]),
        .R(1'b0));
  (* ASYNC_REG *) 
  (* KEEP = "true" *) 
  (* XPM_CDC = "SYNC_RST" *) 
  FDRE #(
    .INIT(1'b1)) 
    \syncstages_ff_reg[3] 
       (.C(dest_clk),
        .CE(1'b1),
        .D(syncstages_ff[2]),
        .Q(syncstages_ff[3]),
        .R(1'b0));
  (* ASYNC_REG *) 
  (* KEEP = "true" *) 
  (* XPM_CDC = "SYNC_RST" *) 
  FDRE #(
    .INIT(1'b1)) 
    \syncstages_ff_reg[4] 
       (.C(dest_clk),
        .CE(1'b1),
        .D(syncstages_ff[3]),
        .Q(syncstages_ff[4]),
        .R(1'b0));
endmodule
`pragma protect begin_protected
`pragma protect version = 1
`pragma protect encrypt_agent = "XILINX"
`pragma protect encrypt_agent_info = "Xilinx Encryption Tool 2021.2"
`pragma protect key_keyowner="Synopsys", key_keyname="SNPS-VCS-RSA-2", key_method="rsa"
`pragma protect encoding = (enctype="BASE64", line_length=76, bytes=128)
`pragma protect key_block
lYvhEjj3nb5oH8uSNLeXMIy7nJYVR9CgwYrS2YsK1wH0yG7GgJF3h7LWVAsRpUASOB7rHmuPVhb5
Ot5CFu1eFeE97Zpvi2xwlrFd2yOm/xOs4mKX3gkTIBIJmAKj42AUYk/LR9j6mOwXFIQmoZqYXHak
Pq2yC2ljr0hY1gwTFtI=

`pragma protect key_keyowner="Aldec", key_keyname="ALDEC15_001", key_method="rsa"
`pragma protect encoding = (enctype="BASE64", line_length=76, bytes=256)
`pragma protect key_block
Z+2GQWpqmewONlHVkL658DHQ1gOkrvPjxsrm0NDcBmt2DgE1WctRC0/WtmZNRR2P9xNPEc1AnD3g
x2bmQ9ClncBm4tJJUerktYV7SZWaAFXLpL0mImalEctnoiL1emAUpqT2xWqYmc7/Up4fedi3U63/
6fZpFkfLPe1f/3mRlu+DKs00gVRP+t6V+01C1oWFsyvdyS5tDx/D7YWjpI8AZn7PAxGanwdNWWSB
/kAFPcC2bUzb0T91+nSe2x7K7ugumFrWpHW6iiuiY86OlLeqrAD5SZsqHhPT9GqJmSzj5PdAcMm2
1N7wj661ojPTxlfvw7ydkwisxeQEZRQ1H8LwwA==

`pragma protect key_keyowner="Mentor Graphics Corporation", key_keyname="MGC-VELOCE-RSA", key_method="rsa"
`pragma protect encoding = (enctype="BASE64", line_length=76, bytes=128)
`pragma protect key_block
NWkv++1uc4OUvmLLmKamw2rSfdpVbwBET7oFkV2XGR6y3sZCnAwLR/UY8EXqGYSYtRzQMSec4n13
l7DB/8txjOrwXvZKfRBpPdz4pIT7HDh50CC1gJaraDaEr18dxcLyq6t0fo14o+JyrAxZm7/nDg78
7/uEhQnwCkDeOEnusng=

`pragma protect key_keyowner="Mentor Graphics Corporation", key_keyname="MGC-VERIF-SIM-RSA-2", key_method="rsa"
`pragma protect encoding = (enctype="BASE64", line_length=76, bytes=256)
`pragma protect key_block
RPz1UvQF5/1bAGbmkE93ADh5aKEj2NdkJKJJhSjosDEbYcFH8ZSL5Ew53E1CBLn7KjAnpfOLAKVf
fX9beeVP5C5vU0n7ZMu9ISDuX947ttq4eCcbaV78UxB5l1Lj8hlouzML1BQecqW1z0mUCgW7CBoO
kvS93cLpph/VpfSwuTwO3q41V7Gxeshrw2U3zfZGHMUL2TI8fX+U+qCt5oG7UGDkIiE+SZRN8eQK
SY18ZEkuzeSrAbp1xn25WHjeUYF1dwHmcNf4wRKiww67b89Lqk9DBKAL9rsw0KWuua8qjESM8t3w
D+f6RYj2AciBO842MNa2LlXNkWM+oLq1CtukmQ==

`pragma protect key_keyowner="Real Intent", key_keyname="RI-RSA-KEY-1", key_method="rsa"
`pragma protect encoding = (enctype="BASE64", line_length=76, bytes=256)
`pragma protect key_block
QcQzkZp4Sch9TwvI82NYHoYu7Fu4A68g8HQ0GQQvhgP0VPOA5fVtIXlGeuCjshtvB9SbR/JdhJVW
H0AcjAKKgHxZK+en5z2azbfr9d1BbF03MjLpFIxdwUacvQfXpyvYKYFtjplThociLLWtOUmXj84s
4nP0l8PXdvTblIHap6SfZL6Dhv1jlcCTvUTUGoULVvQRU16E+vFCep9sJnLwhCCldBnB5vBZ5TCu
AXnNJpF2Gx4Y+BC9c7XyNRkVfKm11TUyI3pc5OcNWX+42CRvLbMSKG711f5VO+yZsWi9YEWqMTjN
RN18y3FwbJ9g/6K9ZswbGNgjRnn7l2PRbFrMKg==

`pragma protect key_keyowner="Xilinx", key_keyname="xilinxt_2021_01", key_method="rsa"
`pragma protect encoding = (enctype="BASE64", line_length=76, bytes=256)
`pragma protect key_block
Ic0gE1G8ZymuhdpWjbURYCva14oPCOYHWxeY1WbqEo4fRdhM6YimsmNp3RyJRpeG6TFY0iDQtGg1
f5g5G1LTD2KIG+dBZyfKNnTE/ZOWrLJOblPxV8gmBtOye+53NJXzi8+oEuZceCLJxPBg1t44/kD6
M9x687RC58J0HT1/+RsMdCvAGIhlkdNOkb4+dhOoGEPVtNJhV6u4ccNdcnLz1ZaIW6yGByR8UXna
8XH9yb/yWXZzxveULhlxfYe5edpqYlF99QdUnueTFFmCXxIYP4G0xwFM1S929iLWZUS13jbam+X4
5SLDsqw5epDM/DVK5Cv0VD4JajhRoM+fGT/I4Q==

`pragma protect key_keyowner="Metrics Technologies Inc.", key_keyname="DSim", key_method="rsa"
`pragma protect encoding = (enctype="BASE64", line_length=76, bytes=256)
`pragma protect key_block
W34Gq4IReWdH4guFD03wBoHFTA+s1wgkA3uEFz/xWEihtgcet7BzSoGE0K8FQKLVs+D+mR8yPD8Z
vuUkN7L+imyxs7FeoUUpCBNbo0z5XahETBApULQzISBGdsC2f/p8wwDdoHY5E0UjcHOTr+Pah6x+
Kb/OiJAA3/B3geutymFuXHhdGJVoLS30F7CpbZpHTVoZZBU1TgUTFXAySsVWu7k+NMAoSxDKr4k3
10DyqW8wuvTaTG+NdumVzlwtmHHXVSiGk0//Q/9EJmzEzH0Pi9m/wmiONCYRmb0c/K5YHCIs7xNF
nWpl/fzOUJQequCzR636PCmQz3/wSjGRil3HDQ==

`pragma protect key_keyowner="Atrenta", key_keyname="ATR-SG-RSA-1", key_method="rsa"
`pragma protect encoding = (enctype="BASE64", line_length=76, bytes=384)
`pragma protect key_block
iEsUxC8JQZnRxQOm+O4jwBmkm5PoeeMBxaBqVOvKpTXSyjvbLGMDYSb0fxpNvdSJbtZpFIPnAww+
aq3rl7doHEf1kjM2dC4rjvZWa0jWRoJIANcbomcPl6IeiRfAUGCGIDrNDxK+Y3GNvZf2de79ApcB
dTaCVwgrbloNzIJwiJkRY1og57CtPhYfZGFMkwwQ1yHtCyOiuh1DFTM1HOr7jtC54Rj43wY2EpJp
V8vuUqRPQXW8kinGG+26i34AsoOI/xAYSbvXdBHrgwQSzEVIApd8q+QxH+P/twlQ/rFGh9QkEtsf
01rrVJSI2TzVwOQBjP9yRmeHw8y91krSW2dGHHjOd+HVO8Mpbdh4nOvQiYQjNK1lqwInPGOH2bM6
kuUfNcfP9+0NlRUDVuuhbzPVr++hGny3Hvo5Aq7bQqtKrYhqiaLWIWoY6mFPGyfIoZrbVClEO/oY
G2CKj5JTQTRFxNUtusbqdXg+69YwdnuXoF9oFfaVJwpFYlKtWBm5LeRv

`pragma protect key_keyowner="Cadence Design Systems.", key_keyname="CDS_RSA_KEY_VER_1", key_method="rsa"
`pragma protect encoding = (enctype="BASE64", line_length=76, bytes=256)
`pragma protect key_block
YKagekiHOyMnMVPg7PmagWsOMo70GABOzboT0+MRxNHoWf+7KtPwFZmbZAZPMjbv2wgx5vSsG1VZ
GZlduGJPTey/Q2+Yx2fvgCJb2dlR/HDmPB+1X4vVosJEw5nD6m8yWJd0L+NZCG6gtRelGjAxjm68
yPC9qOiRc6jrOM91cmFC6Xi2jeY4t5FHi4zmBceasIzRWIBnat7p0fZ3CZaaY76+K02CE2jND22R
W0XlRGoYVtWNukn5s4Z4AkME8oKdQugjp9rNooVbn7sWp5td9RHT1ZxOWgINwiHb6D9MOnsOSGwz
2K1jXhGDdXe4TOnFPIn6VglS5Y05u1snfUxFlA==

`pragma protect data_method = "AES128-CBC"
`pragma protect encoding = (enctype = "BASE64", line_length = 76, bytes = 94272)
`pragma protect data_block
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
`pragma protect end_protected
`pragma protect begin_protected
`pragma protect version = 1
`pragma protect encrypt_agent = "XILINX"
`pragma protect encrypt_agent_info = "Xilinx Encryption Tool 2021.2"
`pragma protect key_keyowner="Synopsys", key_keyname="SNPS-VCS-RSA-2", key_method="rsa"
`pragma protect encoding = (enctype="BASE64", line_length=76, bytes=128)
`pragma protect key_block
oESHD2Q5NORrmTVTCApB+YFZJwjA1ezq7U6VZh96by+ofPCvSFp06AIoCLvB4BhPvxfob6kIkBpR
xVCOLM7HsDk7nO1JVWiYIJ6okoWTA8hAlPj3sdGuMwRlZNSBKn/c6F+CW5Jl37TEGotkhycSB3Bg
B/uu1THUZwIG87RPahE=

`pragma protect key_keyowner="Aldec", key_keyname="ALDEC15_001", key_method="rsa"
`pragma protect encoding = (enctype="BASE64", line_length=76, bytes=256)
`pragma protect key_block
RovEhaqHrFqzjckk+DIWG8LQeqg2Y/nACQDyXKKtSav7YHlgpKmgHZnsxwwNpqrqVRGyjTecSQ+e
6Mr/Pi9au3AgJVPL6VOgwNVE0yj2LpA4LPyWzxLN3+DiSDmsaCBNCBlVQi2MRKUabou8nLaXldbL
+7pv4pYhQdcyjDzuC2dx3HmzADqstdEiyXeU3ktJ29CDLDmGwDWdmsrl90s4YQSfBV2nj4/Vut3L
p/8dzphf1htPaNMujMxxgp3z4JzUEDJJokDL+gNutEEHiaWpI3URIA5v22vJu+NPD+eEraSioHfL
DPKAajZTwK5FHnonu4O2D0co8GWqWW5cUqZz9A==

`pragma protect key_keyowner="Mentor Graphics Corporation", key_keyname="MGC-VELOCE-RSA", key_method="rsa"
`pragma protect encoding = (enctype="BASE64", line_length=76, bytes=128)
`pragma protect key_block
jBQ6Th9yy7jtKQD1h235YLT6qO6XiBaBKGJrV1Z8H9M9ePJ9R/fA8E1okt4LyBvoWjR7tmCbIg7A
0/vuKOogkLtDE/BtTlp4z1iurO8rQrAcdZy/e+7GATawyJxFY7kZhnXASu9zB8TiOBELSlapkpxe
WuAzXLde9FBMBkq4RSc=

`pragma protect key_keyowner="Mentor Graphics Corporation", key_keyname="MGC-VERIF-SIM-RSA-2", key_method="rsa"
`pragma protect encoding = (enctype="BASE64", line_length=76, bytes=256)
`pragma protect key_block
eucSNV2Zbm4zYc2tIGRlGmlVM8+WHY1NHe9drZdgDhGPOHz8PTqHapfnZ1kWuTLtPBLSMvcXNScn
UTvpULofBV6qD7WHLPg7UJcjpZVDL69lk88chgqrlc/RqaJXKNVv+Ubku53ZLU20uZK71bNymjSM
855RVWw5lvTHTCNC2MYIS94Fmrzuq8i0+tFh5qBKkHK2BC+fD7xVyyfuh4mZR2yr/hRs/emoI79E
IKoJnLiglVp6RXTsXFzZW4pIthbjWSuZlOQvoYkS2RMj8a0r9lyariphRQunoudc0bLO4Phk578c
40gusaaS/MI7idMT7k1Di96kvu5mHi23loRcZQ==

`pragma protect key_keyowner="Real Intent", key_keyname="RI-RSA-KEY-1", key_method="rsa"
`pragma protect encoding = (enctype="BASE64", line_length=76, bytes=256)
`pragma protect key_block
E/syLaRG2Ss/xTTkuAkOKXzm53+rCptYO2DkVukWhvlLmEB2daHCPrXt4gKeuG+0hIGWedSwCiLJ
7KNtEAiTumJ/j+3p7s3oXN9ftCSRolXoACsCclEAmwYjVM0ubCXUx6JNFOGt0yDl2Jsd5+W10mSJ
bYEKvRKi7koXM/eYJqbhTrtsrHDwRJEY0JVUPh8EOkLLqaIKbnjb6ENEY6qZOamp5PaWsSS30gJM
N6fB8D1AmGKnFbfY+d5TexS55Z92aYcAHNX2XwHsKnm45az1vHeZ0rTEU/oONIaSZfikRni1iDBg
x2GOue6sLiwxTEHaVkTJsOVR4mx0VsfFxavwRg==

`pragma protect key_keyowner="Xilinx", key_keyname="xilinxt_2021_01", key_method="rsa"
`pragma protect encoding = (enctype="BASE64", line_length=76, bytes=256)
`pragma protect key_block
dSHHpkQiOEzzKs4D71WVyDXLpkKuR9h9h3pBLtnCq2bXiwE/eQHmk5HeQb+qREg0Yv193OukqaQz
RZyuF5GQcqOpqFHMxO62HQ2pdjdpMT5CC7gHvmgiw9qBkJJrXpihIHER4X7OF2iNUfeqxJ8eiSz3
C0V20NlIwKG7Mxg8MVj++xmb32KMUqL7ptikkym20vVdhecVMNvpPoXp8uvaGT7991enWP9HGKUC
9kLY2DEYwRGE71UJJLGWo4n49R50ExFRj91xWnYfvp7uJsMNwnBp5l3GTZiMELX2RkRVSPOHr7l1
n2p5Vq7Uee2drny1IxZ/4c0hYY6y3QWSEqpESw==

`pragma protect key_keyowner="Metrics Technologies Inc.", key_keyname="DSim", key_method="rsa"
`pragma protect encoding = (enctype="BASE64", line_length=76, bytes=256)
`pragma protect key_block
HUtfqZ9dh5oZTOAt9a0ebo+wQbzg3izFQ0kVqZN81S4cBjQEF53WUiVlTKBDVjvLNUby4Se9WZjj
j86TQzuGJxLPDTohmbytErsg5JrlXHbHGwR4zGNGTbBs12X7PkxtS8wVCp+7b1rX6pOGOPqm6FoG
g6rZY/bTzVfGYF2CAOhjJUqUOXEAKnZRehspRyiBI28/ZZPSAUD/abKprW8PWCxMx2zPWztZz4No
R96jgvHezNzB1Ta8W7uRBFTMp+XVSToxTp2jzSXJZ0V5xJl+gdVjAMmf6+te2vqrK2wDWdMxk3Sf
iyLI4d0s25vCybcY2fZWacq5iO9pSlSaOQWgCA==

`pragma protect key_keyowner="Atrenta", key_keyname="ATR-SG-RSA-1", key_method="rsa"
`pragma protect encoding = (enctype="BASE64", line_length=76, bytes=384)
`pragma protect key_block
vYYu2Kvhv3RZi0pFbjRTQ/BBwfilCrGpkMls+Dz6HBGTZvSaC/anWgymoDS0XnoSENGG3Pz3EBF0
19OqLbyna95IHFe2bA7f8RgU9SEUffZ8eXGigfOjAWpZCN07Q77RkhGUKal7okWe3Q6xHtZy83l2
kW8ma3kOYL7GzQjtpbP3lINHLMqpGEo0dzbOHiJ5r6W5U6DsILGsoLQOXcw+MwrevvNRB0KkSklj
QnL8K2AK8PIsJGM6F8dj5KwRYhSBYNb1opuVpiJWlbHgADoeM+dhiRxBLmnaDE8PWs1ReY6uMzzH
SvvO6UEyxQtvS/Smm/uogr1eUFedUaBHPMEXnYlTAv/SKrh942GeknsqfrjGkZxWTN2NEnvpRUwT
fS0pyd/Err0s94b0srmcTYyxZfJGRUct2T8MCphZFaScAlhn655pxW9RaHMfcvDJUHpW8Qa+KhRt
9CWYScPIH6YNDByLQbhKL5BTpAYMNYPF2W7vM2ZzDob2NB7m6GGeKRr3

`pragma protect key_keyowner="Cadence Design Systems.", key_keyname="CDS_RSA_KEY_VER_1", key_method="rsa"
`pragma protect encoding = (enctype="BASE64", line_length=76, bytes=256)
`pragma protect key_block
QSNmIeTT4pBji+CTjknWXN6sH9Wff8+t8KF+AC3fIoIw08jtLtShcB9ZGeEKG02RGCO4lNIUf5YB
2TVYk6EJ5XyCav12qDhc60n56UVrnpfo7drorY0NmOypuxECgO43h6SDWp9W7px3r4CJnQ4+X2Mj
943GdP30WfL5kbWHZJC1Dz9cBIqRa1EbNXvvAqBvRPS2+aXBXAPOC4rNVZGeIUspn/33IW3yJLSp
Jm5GIct87ZuSoz8+DXhUvsTj4hq8lgirVhfz1qhHm8SfODcE91FGUPw3vbpGWXsBX73t2zxFC1Hz
/6m4YqQJVxd+H5iGE4kbHxHyHnH7FIerqc8Phw==

`pragma protect key_keyowner="Synplicity", key_keyname="SYNP15_1", key_method="rsa"
`pragma protect encoding = (enctype="BASE64", line_length=76, bytes=256)
`pragma protect key_block
UhfxKxECbuHK/o9ZExa2zP/MIPmFXuDNZwgpiawuBmPeRI1nJsYB7vzbBGMPKny4yIHLT8mHrQRc
fs05atkjIAbLea4+WNoCdCeg7/0PzuodM1ol3it6BHQ6Yzq4mnZbzlk8Xtwmk8ACAbzOr2SYxYWX
ueuUlimUSRusIe4+NiPvzbfHMAOVPjdmSY7zaSyeJuhdAR+fUGeHy5B23Xe2X6cDPeJ75IqcBeul
ox3dTXi3L8r/s1bTKX3FhxRyPZuh/xCWuEajsF2fEYdwWHKtLX6IQniLBJ5ZnVSS8D7IYPsvV4t0
9rWJqto5O1n3rAM44OvKvc9pOYXJupuv7g3gWg==

`pragma protect key_keyowner="Mentor Graphics Corporation", key_keyname="MGC-PREC-RSA", key_method="rsa"
`pragma protect encoding = (enctype="BASE64", line_length=76, bytes=256)
`pragma protect key_block
fmo66vhS7nigYtLDMjdj7hgUnDG/fnO+cIaY/3qHrcwT7u/paj5enLuWHovegu9O9WRq3pPNnjuN
6vZRpuCgz5p4VAV7dVg9fuzg99BAjThp1Q/+HIPfdQ2LM14ZpTh4FXxthHGkTyS5PJArvZ3/UMpW
zwfdYd5+k2/emJ4/nuqoJHQG8k+O5EjSprLTvNZ/wrE1cT/fW/Lu2pxI4msHqVVYAXz7sJ13cQ+C
7tKxCV8vTyf0rpStdE+kZXg+jrc7vFKuPJO0U9axMsC0nXyeYx2jzfAHptGWKvfQaPg/Eo9mgLyN
qSJfFS6aIycuxNmg7L82WK401aWhnUn7GNrudg==

`pragma protect data_method = "AES128-CBC"
`pragma protect encoding = (enctype = "BASE64", line_length = 76, bytes = 50272)
`pragma protect data_block
91H6srm188yu+P7Trh4lywKUKaKLnvo+dyjcrqizs6MgOV6SrwkR0ou+FMw15Mi2lgNhchXWFM24
YeD6G4k1LRuzY+oojQSQ8LBe8oPkPOqD247l5SdtYyQES/osHRBM7gcU1xkYt7+LOheZzhQSggLv
1eehxXKyxtwf/s6Kfy7dZBEoOyhrmkrP32Iwm/NV93x/A5vtZTXI0vi9zeUmo7J2BMPBncWa3X3D
NXtF0DSiNLJSac2nRNESqrDjCzezmseZScFDDg+lLWbKAF8ScMtnZH/KKVLegSoJkKu6HBDZRFr8
7ZXO57l+JEQBxvWCb0gDuBLDNyV1//cHSu+l9VKAfvyzbeuHEbXpVrTQHwuhrjeacTnR79M4Wham
EGZAWJUIduTSgQ/2vagaSiOPU6F62X0APnwy1pAscffVmPNNln+YxHQlSvNIVm72hKyvkNQKekBJ
rBAXWuvzYJYti8oGQ3WlN1eHytWNsdjyDfDNu5uqlaaG5Ba2YyX8CoCq8NrTPTdMoaj/GD96g3Tr
tQ25JiRexF9+H0Cb14jR0DMRkLHK346NG3I9hviG4YSUcwLdCTuSMC6FNpirWw8ZZWOx3txU7La2
5AHNSKYQICdsV/P2V1i/xqMYdHJIJbUoHma7iH9t+J7Rtif8BaulC9H9vNqhK+8l99s+2cgTfGv1
J+foQb3cuB58XCYYAqVwYuN+Pb0qAAUnqxmDSupcgtXtCNh5IaEWZ+mSvZyx46oSrgRSJsjZTjua
lkhfTrU1t/GLmZ4MAIKolbhxKUl/CGPZDjrw0yNGZFwGJP0Ci1ks+gTFZhO8pWZBDqCqPV8HgFgt
9E99u88qoJHFwPVUw3H36I+sYWuX9fThXcsZDBkCyFELGKPPs5il2VVm0U84pzgV5Qtcf/kBOn+1
zvcBSDDHKSEAXoFImp+0mc9y20YnoT/IwUSPioK+9J+8Iuf2x7c5J918nA3cy/nv0YCyUQpHteby
yadgAhIMRVus1fZ6a/eZd7hmo4LDXJ7yh5dwQkG+CPljT0P4Kc8sqXtNEgtUp/vFumPHfA9ou05t
x2xABJrXmjgwrDtOagnmLpu0cGkfXGEViqwP8EpnDOYKmJ9qy+nt3VsXbzYRRMjbordwBZQApPnj
u5k/YOFf3mc3ZiqxS161MXPQiGZVGyhj8f46t37xflH3klj+TbqlxRKCBGlHR29L+9tDV49WPZEM
gpDlGd/ms7y4gFc7c4LVLk5KzjNAsNiwMglZHD98I8SECreZ4fJddMFxRJGmCdvb2FbcQk0ZSnNg
8Dz7E3OQCS8h3Nv86yw2Mwosdl4pJZD3FRUPvhFr0X4nJdePXH1baJJoWEHYgtH14dl3W+cTGRJG
ERIvHzIKanpehT/KOJPbQIWhlmJU0uCUkqGJpOnDor0sUu6due3JqXn43yv0X8RhFSShr6MzsJ05
YixAuSNMMusVVBBgbc81wgdBwtrorosgsif9vEdGeCn9CpRZlWdkiF9QOQoasJqEjz56RlCbPJhP
K9UCKGR/jWlaDD7i2T75sOVgBqarkYyabBNrboPx1r5EixKBmzvNONSmnDIAAIAyN1yo3WpfgN1r
2SDOQ/5ufJIzm9OIP4YvSOzq5dzZ3OwuQcyXoUoCYc5AExcjgHFJSOj91TaH54hEvpnTKGTebgb6
tuFbeumTBFWt2iasheW7xUGCMaWIAsyXpIaQp/L7PODclp0KeyVx+h75r5rQq648PyuI4QmpobWB
4R6K3Ixg+no3CFcpGosCbvXhxsSp8uMcQ1Hz6UFOYkj8gpf+VZAz3w6THnBv7gQ9g9ze37jEMq2c
3eg11ZNCIQYoSriwZ8ewqb1EQ94+Ys6P7kC5FtagL7TJpu/ahlDzxS5t4Yp1oRP42c43ZCwShl37
92Dlfaj9H89cmD0EgqfRbrnnazA/EOUyh05J7K5KvALoKetHtN4UOokzI4pnt2HBSgCdpG7MdR+g
hPdfmj5RII6CavlQgzB1RltSovnzl+zwvGlabRtORbgVvrUyw/iZebRB8SEuKYahnofxv3LgMUbd
5DHvB7sEW4lRG357ubAiQxqY33JgJ1G5cWAkXh4bUxRVngkbOL2tXeVyn2hUv9364i2gSkOAKFl1
XcqyFIJuC3WD5VJ8ILOf2yNOOIr5zmZu5MTMAbAnOxxqP6txyfa+1yHXZ1/8f8CtsnYPyTGmMz9l
IK9Fo0HnQ7DnoPsFinUQfIM82eP4SJwAUWyrg9ktDawVHu8mSm76PPmi+LEZSWFD5/xDEyW+7opO
mWm7LHNtPGRv27Xz23r2gGked9Y6x75oDveFxQ7sVL6gpBSkRXjrDwjZFetTN9IXC5cHQm1pdtc1
SIjaMXjIup05DlphAV8TK2nABrfZYsTFOzjvzx3sWODTrgw5ZSiESUbQg0nmuAINrL1GPm7aYDed
Mj6de+lSXXhNz0P1b60bqRaVZeuVHjCmmwJRnr/1ORVK9T159Rs7y/j8qTvBRDAp5H+ewgXpOJUl
9EDWeDpozzNp5i5lv5JRdQO2addDFsMDyItezqsS/6ORkbYx6CXtRUmA3/hNTHx1I3d3TZM3kmTE
5/B0IQem7K2jO+C15SvynnvjKbx7POwYBA2ETeIHQgn7KE+ekoFS/UrOvm4JjhmUnfYaQo2Ybx86
C0JCy6dNjUm/p8HgqYJ+JOQDRnVcHq3AJY0J7kUi7WjVLnfhCvo+SnGPoep4Tl557EuesLKRZsUV
nEwd+xA9YmKQiWJIhHc8ix0NjsizrePGLYrV8gA/xFd1yZzVrzDu+QmkbSVeKTfyIZBLTIRxDESm
3nqoeM34dw0GhVGWgQfqZygM9qI76ifSqmFKZfP2rISmrMPhg9XbdPQBwQ8Zc9eDEr4DeNxWGviT
BGkpQz1vGSUmMY/4B/a0cP+luQzuIyLf9M3lRhPXFKPy6Qh+prGB4K9UTVAqCPrccXXX1rqPio5O
keXNOVZe/U0nUV0gOmTz77A7F5qdUEkPOnGzm2gwnPxDp+JHw0DcgkKxKm+dXm5YWg/jyL7WO6/S
zOxuXsYcZ9zFZYjymjWxQ9LwaliV/ZVPy8w/T5B7ExVMjFKPxTDhxmcnt0GjLuGI6Hejm08II4C2
rtKy5WogNww0woAS1Mk6bpPXOylKbw+37ScMVcF651vIXtP+baz8H4qBLoFtqmTd0zc8RoCQ7Qnz
w474/lN/+PTzyNOyZXgHTifBEpnffg00hFJFdIkUdU/NJjgnpt3eSfQ4LbXG+Mp5IRbveueskVsL
R3fRvJjAaAeHU7f5biFAkxDztWlknsa4uH6qwgCgCyUCin2DIkpSbq1pg2rcZrX9OAfllNa/oJ2b
GtcVUR68+5hs8CFAUr+ZvciReQM3ytstXGK5+TyZJnYht0jcXigU65tMaLwJnZKeVgpzgC1vqGxL
IxmlnQ9i9eZpKNu5TtiiaiTDVqKychLDl4+LVz3PSjGPtctOS4RUCzuEvd0kWmQom/wbimKfYwlX
rZRW6wXriFyh4eylHWe8gzFv4pyii/9shFdBCNW1DlX74ZtoG3RzBQH/fQ8mktOIkdbTsxiS5HqM
zbTySBHFUaWr+yVy7mKOcmpCXMpn9uXiQ75nbF/PWKYH9OdauUXwHpIo6XSZzdIVk22fAo+ZDzr8
95WXn4hOLkQW16znUSAJ/HvElBazC14R5tLI3X6wvnrsU6gHPWHVAaeqVV9UUDJKM/0safIvXayQ
UBao0ZMnIq+t30jFTxidpM9YMGGV0aYrwmPkGhi/OSJ2U/vU53jEDFpYv8EGen7icP95fnbIsuBk
G9x34E4W+iHZAharUxsfCa2sKD9CAwPGb7mNDihT4O7Juoq94j3wr2WWG0N/V84nQcDmrPXxLV8t
7CfSTzssncMsABsSL1go1p0VM3kMYdbiBcPnaQL7lWWHxdfyHJwr4quF73l3oy0DbT0VGM4H9eVD
RF7geRkvqoZoid/rn9HCutxgK6ZfCLh0f2MwvO7i7W/7tu2dvDopOjxu73FiftJ74bR4WtxqYTkt
YnVzvsYsXh0bLQjIgkYfZjojQwtIYfVCrBm81wZ8hVDUkQR0zdQeZL6wH0sJwyT5qlkfMvRzytJx
xuxjXmxCK7pEadUbYVoU/U822zuWSkQzYlSOAIUn5kYIPCTMDEQj8MTnjNuPGfJzfsqchDFO8hvt
Naa5Eu+fDakzuwpWxaQaCsr3sUoEYZfpeWie9cJIDmBDN9Fnw+C4Yw7lhgyE/eKcX2kjNzWU+MWX
/BRkkN8xOKOvlVBRT55BJOsua1m/qceCle3NkSgzN74nHpYo3cVJvU6IpWJQLQWGU6k+pL/3ypZk
EU3adSn9wuipgRR3Dl9CFhYyQWsANGZJ6/12TCiYLKTu0LZ/YNXJUkQCDfVAhDJgFTRwQ+mTXRyi
ld+ARQadZaRH9qQnBogF2DBCHrcvbF4yMu70vZZXrzGiY+ZRtdVP71iu9Ij4W/yMKDzDp+YFGiBM
4ADZpPpnkN8UIg90gRT7LGS7IhKC1ofFIITki3fEl1RguCxtqA8Cib0CHvEPSgpeeUAczE7maQy5
qZAEuXWrlzAceNtMjK7EuxQ/0yiV37jGCknQqp1LH49g6zEAWHtA2Sy7zSAF5zucKqVzBAn8Uj8B
j4DvXG8hUD3YK8OQKwxjmyUafDQmxm9aU19hhd8vJMAegQi+StLL4ZuG8pkE3G/PiyxiD7naSwb5
SlkAvBfeqvjqeZCnhjYQJ3FEnUr6IPOK8WR/iwo7Ycs8nHTU9Y4Qj84DOUserZshLq4k8lXTm5/8
kkqXupPXssjG17MZYUF7T+8vc9GuuDLPOMoV5dh0QY26pqY4UnZiKpTYaEXwYayiPjEgzTr3Eeyj
ZiR34uipRB8odd5Zk0adstWz9l+6TeZzjZcMoHiu83X+gW/Ij0U1eyKW/qansSbis4KJJ6K5NRXL
BAVFh2rY1OJ0sMDNTgBVZNKj4L4rm8bQok06+bWdk1nILbvLVbn/VOUMjvk/z+bvcsW2fqhBs0CP
/npOSuJY4c1xBK3xaNUD8fng5bxlS5FJiZMw2QhrHTKyqWgAlsBmoW42PItmw3xy8wZoKjJll+rR
T3TGt1GFvYj3lAYMDYMQBQqLSDX4xqh+Ml7SWBm1dD6t4D1WkvoloS89en9R3C44WAD7H6fcoEk0
TEA7hxv7OVkXqdNO+QKWJ+dlyoJuU0wojfvVwWjkQ02fFRks7SFppszdDrhS+qGdZm4lwDb5OwWG
t8XijpdDHMAxlOyOyG5EZELIO8ZxpeUkgItQJgIuCV6kegpum8tt46/F4jGvGeZ331G+L//Qjlcs
p8UcX0q2F3KbKs7Vg335Madllw3LxogOZIDZnEB+vtfHG5qoztw25M9GrH7H2kZ9FPLzSWUWZkvL
kcxs3VPWt8UX2gQLMMbZQ9q9qzfM3uH/rDCfTZ6NyCEbhDozwT8hkkXMK/sXoJ0j0ulxgFy8JsMh
8xj/PABfHxbVBq1X46gwniRhRDFmM0pjnbf971qRnKhNdMzEGLSPdoO7AYCWVOyi2B/hxi9pU7iL
8Zz3TDZ6fBtMZAo6agm0AXsUhll23FlyP7im2FMOL8vl7bN5ZIBrxvsEU7yvtOQxI+Q6ePlHT2ts
BlI4czwD4Cc77HWOiQ+4fGZTnOsRgiL3uThjVVQJiEU+z2nOZ1bcdKCBJLTcB32/r7Ph1PDvmZM1
SwRxgCfK6aWOoIV4YgPGsx73TsrsxphySXoi6eklfiRnMLZbWeEs/7wcLCFkruKTFTbC1OCFZaZ4
NuhMe+XGKgg1LrpWlnU4ZgL+oCkWHjKf0R6SaXQm8xUeNQ4UQXs4a/4wc814ILVLLVT0i1aZV4Om
Eq4p7jHTPNOFxrDSJuA8GpirYlvM9EKcY58Fkhzy/rIxftEDtQjzn+3J2wm2dh+lpFKSXmN/tStV
meh+UFDsqBpYim8BLAZZNZJXrT97Oqt1UiDdaD1XYYX+crlSpjFSUZWHf33HXyw1qbEU5gnp9ecv
CPaz9p4RdkZyNmHG6cOiXTaKMQrmbepxLEtUIpyPcDDvGEe7YiU6coTX5IkO9WE+wiDdg3szVrvi
ej82jgnHMAJSyrVD0Q3TGFZ0bImX6VnBKJFL5jZSTSu2fYcfjIJXDCmLrFFAN7wE8ciFGlRDqNot
XYg0GL94kp76i3cssw74ry1RHAjVQqRk1dXmfVKtAzDDnpXHR2bvXcK8uG5uNhdlAo13cyIB0iMe
d8O5hwRUBERA8+KVmdonuwa6u4UR2Gox4mMRBpR5mktEOcW5PvnZWt9sHi2DYV5Dl6tTXsFWI1qK
xO0WrlkuVDfKeWlSceH75Di/DxJzkhzQnhEVvuxnfxjhkPNsSG8Elo8c+4g6+RDwQ3yf39HRnoE3
+rWQiFFOTETNaDiSsjfH8uada//3jChKSMi3nK4AhGThit+h0PhD8pZljqUaGRNDxjfmLSL4YshH
+PYI/znBAfkrAz43JMqNVtO8i0WNzOtpEOl//Wx87/3SVku9Ob2ZwYUPlrHmmOOQj5q0zDo6G70G
0Ch2Zc9wqQEiWyLcn0lavETYP4/XvL855NoMrC2ZPR+VlOnoXcko04vN559BlqrvUORA1t44jABr
P4pBlA3s8nSTPPhM0u/PDh5HdvkfJ+9SYKrwj3pq0tnBJtYTbTJwtEwLyIho+6rLfwEYYMiDf6eK
lh/g+fUoUPwPbmw1mDpy/bI0DGQDoFvEJotAum0D4McWSEQd/y2c8Ucx6UAQiv7LM8lhy+aEvjCS
zM3MzCc+BIyp/1ck9AG01nyY7WqJre1jE7Yk7Jpo4xuaDxAumLY/JDOX2mKXb6x6cEW6MqbDolME
CW+Wfh9I3UrIQBxueaFyfFRvUNn7MZNedjoC5RXArdorHNfrxFPRkNOH3Tmt83Gd9fJ/lvmeIcbu
1TYQxE921SfOeb6hyiJ0VHbN8b+o/EsmPiv6DdnxK0xNP7M6dZ7kt0+I+L/j3zqQW0NjKZTTKs4L
CwrMyul8sDqxss5/ZESczpT2s6KajyWOGCml3fBNveXVnhooAPvucLPiC8eCpA8X4181mbxHEPvS
kc3NHQtZR9wVkLYUnSFZlw4RqoKjpfxWvn1RJC7Bv+DALak7xQIwGZT6med0B9WWjq9vguMs9Har
uXI0HakJxLLfAFHBQRm43mp0NMJzbs3+JQ73OVL1JR8sXm6cNDMW1HWQa7k4KnFzE0VLk60poPvq
bJVOJGUtpaMwU5cHAETSr2ytKB0vJgquyDAR3gGcDfiw26+EfTBvgH/ParMq4QcQObd54J10yn9p
JeFaL065lPoJzTN9ZXwGBKklSCMociZ1AG5OOQYO9B4KX+RZcUQWKaAuLxEUtYYwPbxmN0IdCwO3
Q7VCmQaWR3wRz9HK5BHL5mGEHr8BDv37ckNNuAzsJ5JaHqy+6s7DqyckZoAuir9qo7ddYoxXVyXo
jrw6iuAPf3sTEg/IcF4BEQXsSOEwcKMXab3n4+WlCfJPbaeEke0/vOF+OjNMn3vvRllMqKqd397l
QwGzmTuNNtBA+aojQxxMI0iRX6K0K0LbrAOXtybFqi1F7JK1rL/rlxRytlfWdxq7hAmFAj7IlSKh
5/worCgE4PSFeIs/RPHA9MlhExXXkzvvH7pOvkBAuLAbjuvqA0ULYNFvCY/Jc0o7CNBNhRKw85RI
oeWzTILWeoijWuVVQcABm3oDdnrCDQExZRAoW9l5BnvaB4/ZdQBf/LH4bFvJPCKsHgDzkU/CuhCt
g4MhF7i5zk2tqyBiG9yXfTFgnTKhhuDAGHvEThlvBUWmM/i6QbSZLBhEG3oK7WHKqU0qgvye5UUS
nEQV9W9OP92vNxt2pe31j05qGE8VoyU8n7HViuaroiCeMOWFjjEURr3vmF+tjPnUj6sQ/ONW0jlS
xoszkumyudz7y7Rv71PynKuQ0m7sYOSUlZyUdXnD9Aeyq1zN47VG6XNyqd1KfmMa8M0hE97pnLFz
lhL/ngSNKWHnDxPjVd+ktIjUSFwWld4D0AxxMGHasrDLRRlwMZWLu8NhqL0SEkhUG17+e2Ryam49
DUTCB2orEgzezUUmCA4Mgl/1E8PbKNYgOZhPtSR1EbVRo7tGm/KyfzcgR77i70DVtNRd8L960/YV
BkRXjTN5qwjivFP6dH1Mgu8pbh6VqOYx/a3xHROKml6i7/8WwhrkYB0JkNGMHUUdkMN8Fn9xlc6F
Doif1tWIkmJolvf+B35oqbGOpvXtN8Muml5r+ogChPVNZgNq+juxXJXEgl94hwthCTaHNtD9CzfF
vlqjhUw9lpdA2PmujKJN01zs9BtDsy2XkkqHRIKDVZNMiIeNN9zW3yjSTJ0X3xWxIV6EXj0zxRDq
L+nVL51xRNgXxNFDjbSuIN1Fdiwu9rtcuLAtpMNH6+glc5RbRewe4w3wo3tPNQFpZ4PQ5pWrhN85
06nl7wBoyBGAeyQx91qdCRRNW4UoYtCtgBcWpKUll59JSlSDlFGE0XugQaSSrWbR/qW2yb9U/B42
fXJ4CvRcwR/awgZAez2mLCc84aCsOSujOnwdcn0SlvLxInuOiYMBb7rqsuPzCHm+TjV5WVB2mWXq
tQqpZ86mAlSdjW8ceDmeytJLkKkByeSj2eprr9MtFRQyz/4/L7oE5O1KrVpmuqyct38eh9CUBZNs
vmzcdLbsVZ5t3i8ehZtYHzw8MzBJm3aLWpfOKgFqmRuMZovthp4CxuPpGPTHlTDu6jsjqckOCKg5
CQOvjxRM/HS9hwlLyfGFdimmxzpzmJAgf0USDhOMyXeGaEJeHOHs0TVdMnaEttOoV3GYEOl3shbE
Gd+4id763uDM6HEBvNnyfVZHDPDqwSszIsHtHUg8o4+wpghMzyOyr7pBNIrDt26onPVfjBKlysta
KjKCsDTfWRnAheAyI5h9bMOUIOZiuXT+4GJxvQxvZh+g8ozZY4uBrnaHRKZbtXu2j9l7ylneYSgS
6QhlIiWCBtGMAtWBVjXMaFRjQpzz02dbfPZ5esL+WYqevSsp2oSGx5+qYZ6+OBgIwaybJXgxvrRg
AGmQxg6bA/Ja/7vHqXoyv3yGjkdbEDCvgcgXSDvEGESmFKmBrFTDlFGq8OM6CMyjqrNwhP8r8WHd
TldVI8fdtOJkoJIul0Cw5fYztu7DNyyFm7U5JdT2yi5MjtoVWlxRZ4itJhccXeC8iORoV1nKdb0S
SeRoPUubF8TYzHiZDriXJEAmlhm+ckJNa+Op94cuRTxuBzJYNMyWQE8gwQPt/xl4d2tS4v/U6PXz
HB+3G6VXrDlLzpeatMA8xs7pJeyogyKDnIU7D7Z0l1eJB85S0fvePumi/1lALrqRnngHag92gH0R
C1jhhw8Hcgzq+Rl9ttwHctsg2icFIUdlm5oyzBWD8HGmVTraxIGrvrMVT0J23nQataBQZ76ELOXg
M2TIPe1xXauJaayBR0jLwaqWa1OjplQI3cbm1zqG6No2qzERyBU85SkbRv+2+A9BIjq84tmECzko
+mamLr3HyIMM6ikDtg/PlmKUw0ZSJSaqhsJjQCq/pJdGIiGisUH6uJdAKgd8hWM7MvWGVmxEdc5U
A1ExBhAICj1i8t2sSXuVME6pXQEogCuc4mJ5U/aYfXCwJ8xrKAdG9Ef40Pq/QVFNZa8AjfBzmdzQ
ZvrkHPGUC98Vw22+rx5gBhEaeR80REQXJQiISHGiuGJD5hYg0yBZbqTm6As18RxOJ/bZhvuOBrQR
TrUev3eRaNcHYbaZ2VOC56Ra9+GXjKEL5uOh8uoLtTWBixQI7QBlvoifbCVy9ZT93cZr68UxBn39
kWSLPig3G7ZgcX/pNTZDX4cYjXuMZXzC/BVVCxsJO9uj4Ev+rKTsf2NcVyj7fWUpA8Jc0VXrF75d
2m+0UO8GEkCICeGanBMyXPK+qfLigY2KAw0RNdULCNkukoxI9bn+RNCPL7cVIom65Vy6sr4dJ6O/
g4v2gHe47NiPeEexrVqmzh/ciqmynu9Y7f4xMD9HyJn0gHUJ0nPr1DqeRn96OmhmGnGG6VG7gfVC
zG3+VxP7iGvMqQSWOulTF42Sq4ZOcG9Yy1swxdFScy6yz7M9DFJypOaZK2KeQRlY7WPjhzJLVPgc
UPj8KZsud9nZVXHzzy7KZdKa86qWcpAJwRapdkyRFjdD2N459+K62UaGQ8Cuy05P/p8Oln/Wek8H
eSiSclMoWkeC2jCeIh2KALz7prdo+9ig8D9MT2vL5pCJ6LHHZi6nvKzEuuYQHzJi+kbXH/RO9TEk
r+pi/H88xWPggdU9JiHhj1YFIBz0eHO5yeAwpX477hxrE3RnQOjg3Kmbf42FbkMHf+ZgvRy5zO/P
jCoOgWfC/V1SG39i0ur0u7sVOOUU2nRCGl9lJdwVXfykqfYYhtDz/9Y/laBGDH0WRL6lyIv65UL+
GM+L47QIKoxjzZkybpBgwSlC5wLFlmBsm0KaOahGsYchdPwJs2T/CEv4kzQMxjx2OT9wwgBrCpTy
5/ax/gZsmwqJ/RHJxd5q9844KpPgWiKKL6tiKNVMcz+Nu2BllxgrY0fycw3WHt+HxHmbuqiLYWcH
VlJfP/OB5BMdEOUWDeJ8nidF31zk6XTKSSV0dOb4+hvrmgO7LxH6EllJIBIYMXHmKmu4+uCrMZET
gNsPP4tunavzdO4px/lAbR8yghGKI+hXLwcETPJhxy2z2WZ+y7DBcGFOsHUT3UUfyysA6BUIOVUL
i82eHAxGPK2D4Cd7A5Iap1glAvHlMBs2PA/Jdlz/dUSNCCN3nKJm2RvKTBkm05CD188SUx8batnX
L5WKHCt+YnJnZBbic6y9ZfayWWmLIv8EBPAw3EWdxegIQHYDnTTLnFURRdtiiw5yKzYpBHfKabFq
FQLOtu+Tk8gFvvY01nCNFQKh7968MXPMxAffbUSCRAyCw0jCHmTCBsJpxZUgp/PhDmb4gh0RzKKh
O63vdxo/Vv37B6OrK5dFPOxLqmqy+t+4ClF1HXk9mshAogNM7X0PgdDMeic+vmC4/YP8Um5mgmhd
jqP8fvtAAwv9EcQjn5Fx4eBaXdPNICjgzBhAQeyQrxxNsA3BVZ6sQ8yO29S+a3NaL11GnEY/pu7P
VslDY5kaXOfBb+BZL3S67fU/+hDL2VyD0zLJEejCD7l0ZT8DuhOLZQ96pQweJoTNCjKs6Xx8Lf3L
HEzuUdRhF9MJx8UhTqbUEQjQJ8IgJ3AbHdnmRoQWNgWRgzD6PHzsIC7ituFldB/nolsmV2jnl+qf
GaB9uJVD+60EBTn4M10sVkU8Qpld2V8JZbHaZyIzTqH9GynebkNtnk718fP58wJNWPZ7Q1UjPy5F
hGYW4dyp2E/MBxA/DmomRg/mcyW1kfUhy33xwzBtZHBUYJOaCfRwthPlV69IOy4Tb2CsgbcDvRfz
3CJH9VjJUatkUvJVyatuHt186n7b2u05/OQeWTU4iFQFWQaVgpCU2aB08tYfk4K3rNRvlsCJMdho
57EZSbXSvzw/BsV7Vb/zUwExFGdhyyUHjWCutYQ3+Yc8dw0aWzH+RIb/Cpi+NmMgWSSef7GuvLlw
cwbGliAxjhip8iSxM8iKTOImxXDtojSyAafGqr0J1m8ZlLL/h6pXi0476+P5YyFxy4wxaxIwWTCt
BHlmeOQn8Qho+1tt70DLI4tsAMHjE5+xuXM6mGdxfgyqbQ+hLozcbJh4dpT9nYOOgtQlbKZA626r
ant5gDWVMnbOCtFZeDUs8Gbe1QEvos1b0uvRQArz+leiRzpW+apujySLHXRbOYm5Lw4F6v1fumRs
NGZ4LcFl3BS4Dk/onAU2w3HFu1W1SC30NhBXyPJtGGyGaiPpNvkUlshD0A2qGGKV0I1Iot+Y9LvW
QL/ffIuDj4GiF/mrOty9mlz1Rv1qnP9U8vF6mzxmbtKuSZe0mLaGUYYEuKOltCAbQJHoKWiQGlsB
qcjHMhMZHQQq81JeXKr1TvLakuMQVKgkh8zCKQKVdBc9WbP1EkZI4zg7IieFbYGG9UMaEHR2DT3+
ZTCwj5QPRCIndjeC1MX9PfZZknwL7lKb/CXDkGF5ZQIezf9kVPnRHqH+PQsr/z3ceNOOj1L6weYW
PrwGPL+9CXbNJDAQ4N5OBRThVa5oYd8wUiO5jXnX3151sfW4JF7WevUWtnR0z4R1oEtGA5OG80He
lv9Q8n/tQZKFPgH74GdGmD67L/p4cU9JCCXwzOQ5k1zb9fZlks96ITlrOS0ZjiNAtmaO5BQA7dOz
a4syGoaMTTgu1vcXfJVC2N32Guz6y85BulRBzd/olj2OjfsxsyIDUflsh9PzZ8V4LAjE/cCk/9wg
qpE+1yIoIviQBpAp8+4HmNLPoVkp+RiM3M+wcAd4XH8wQXQFvJOAYQSVOAOjobLqkHRdGSGmUNT/
yyAcNCVdANZ17PrT/OWxm8sU/UfgSe6kCn4urFmeoZmpUpK7Fhi8RHD0eGHR+RfAD9mm9ug7sLMf
ccxNHXNo7wp6mct1YH6CGWBQteDVkgW5PpQCEYbLPVdL5P41VVvhbeERXTe8LD1apli40OvYBSE2
jXJzCERDbW6xKzfmxfNTPjaY8Ham0xfLfzBch+ANZFfP+ZzPzAUFGfaAVDKn75TIOYBjFeXUjVgj
KC7rPVdZL7dAT95GlJGhnaQBVTbspIBlV2e9HFEnQAXiCCghNB2XDgRdD9NrEcKcxUj4DnPmNLbK
YnghBdP8sg1M4tVJVwuQP9R6WCi+Be08yjTwgz4fi3bYQIew476Xnodu0jHMTPr4F8FJW2MAteHb
LN5Y6R67RuCKClL/cLyr6Ab5U/gqxQmaMvdb4wl41JkFWBR4FBtXVxHMN8+nJRN+02MnEaNwzMe5
PBSK2bSDEHQsc0a+iPOq9j4hQVnzHJeO0ZgbLz7ez958UZdxflRf9P0SSGyxq9mESqkPKdkgKRUi
50DyiPBktpjhKcsmRnYDw86yzmc47ma58nctlpASC5/Pf82qwobGoatirxQ7na0LzgAJfBqSUsE9
kLiChSLBk+k9HFfFnz6MAhU9fJVY02ISCeCB8GtZBMqm98FqotJnvPBRAfxXdn1bhZ2/njiwXpo5
SSBhQSBxaSyITw4AjW3VTwru8rRBaXyzPFqlSquvwlJvam781Oklg3pjYE3sffcW5m3uE7yX8eFO
ptQlSmq4XV/sfvkGhg76Dr2qRBjmS7jgDxKvO1/QzPzfHnFIE2Igfeaky6oQufQn8hiWPPOysLrr
tcAInVP49kB02A1n13/6zYxhAjlCf8ZG9PacpPaqJwHc75sX6kkPRlmYE8sr0uYJD2zTcGA4ocqu
HjsIkT4nIFHhUdM41meAvh7gnl9+upy+VAUa4uO5PnI1rXAcfNb/BS/p24mo0EyruhhY4QP7rR8k
1bUSG20XWMBuvmbhmcrF49GzJrhSpgJeXzC7rNl85pRtFjIx/EWPlKDx1UIlehCbfnKNk1I3ay0h
NT1Z/ra41+DlT1KWsuqG903x0fx5FkpzZRgXJCW5OXOFoZEW4NdQ36+FxQem6Ym5ZMHV6hVZ4l74
+IcoaGPdS9cImNAc/bO/Y9IM8n1SJsgmcdtHxA8x7+2HxJRkYPm/0rX2bE1uK7X+/EMcn318AIFi
WyxZuEhBNjkXxxcUGYy5yGBoKPwcHJweLfCwMAOQyXg6J0X2JEfs5UAgml68beDpNziJWUx/wIDd
Scr3/PBC7lSsnYilX9+7kFDz0vYnDL2IYGAE1Cx7JiupiyOkZtu93sqlFTgaNFSbOAhQjEfwIe4z
wI9icL6isZy62rjkAnhBCIwiYMZfny+Tt18Jk8xBPTyd4n6jRBKNrWZ8/0Vy5XwBoCXMRAS6DArA
pv9glgh0peMRrHVtrz2mW5QQn1S7VoSUG1FjOWGDS043Phw5lOk6kXQe465U5uKL8Ff4QI6gRcXq
zVg+5ByP7OfnjOimmdJQUOnjHjCktgN/otrxmuk1IG7OgjH+LKq2YPPK8AyxZNNcTd7Iair/ax8m
YauQTbn01/hYUv81GiCqGLNoLJqu+/KKgbRIbs2Sm5Cum3NRCVKHN9kZMJWhbzqu35Y3K/kYX3oM
k5Lx4KG+sk6sbvWGKgrEewmMfotUPlm1wWBmpAqKIDzfM7oCLnpStUpoTR6d5/pF5fV5FGcFXOBV
Tvhx2swIcwTtXfp9Q7RHPAPiHX2xjhhSB7qpZDPg/PtgElXSMQCxgL6+VU7CwiMnWbK9HmLW7AXO
uEggHggFoXkUY3Y+akE8VfZXWm8JdvBFXSaoTky5BegDmXNw9QszpJheJUcPwc+sf/2po3vwJhan
tHvNULeiBTpr2sHN/m3/p8oUcoyRJCA4mFday3PwUZ5hdAY6uk+3uA/3o7An1+pSi1upOjaSzcil
GUzK/cH8Bmm6zL37QSS+S4t7Ut3GDAYRfR88DdFq5CRvO+RkZ8YM/Vt6zSABZ1lwsh9HiM8i46Gx
1jJHmdupYVfHLcAlaq9czZi+BN2W6uNgrtugzuek5t5uQXXxh83oxMiq0HtUe2mK00ODLM7v5SE/
kbrlOp+i1D7GavrmZxJPeNfwKatYL6XeDKp7HACW1Iql2Ou2tq0ybQfzoYESciF/iWVc9Q8ZtW3m
D805Z+aAFyrhGsZl2zpTmEtJxql58k1vhvjRUPu/L5zBGOplw1yLCBr40Gzv0VRN4UnDiGgZ5mKy
+9Uo4fXuf3sJY47KjUao61RjCU40zWTXYO/S0BT9/Lu6ccWb4QMxlS3Q0zVRCIekQzj8TSTHYIKX
IyW45PwAl0BzhtoSuqmtFYM/sWZDVtFxA/dBpk33/MqMGN4KX2k3qztWepUsNzPR+N9CCuJAP1PK
SZec3TJjwdpVnwcwebl93AYbuih3K/8WFirlPATtD1AXgw+in47bYEnGcLMe/loM1c9DGML8IP7o
32h0uT1+YxmDHTZm5kQVtj/8P9+V+r7D5m+mhRZOzeGqlFfzDPada4G7DEL3wmr2/hh2MyNcd9T9
OWFwzwdcNS1ygoseeJ/yLUgRHetOl4g2SYg4hEpZPn4qAqVeguGIlLkHdILrH1UqM3VYnqp2ycIC
baBOMOzAr8vIeUcahM3shPWYGdAmboR+XlyNGphS3prLibVEKtu5qZEvjHuYV/K6fK24DYwnSorg
BgvwyLqeTPBz/lY8yM7jRAS0Le6SD0kwBTIKF6V4MyEUxIGMLSEdphgo0gG39tLPOjwZMWcdLIca
Z5pgMWJrnW/t7sNeLJrCzgebJNetzRJYdmfI/KCgvem/Jp9+RCKRQfHNSU6LXSDWEJ6zRDscVI09
Gr8SsLQjFDxzl9ClyEJdTEA+MRf0jQWATP7Zj25mn45mwU+AED3JV8S0XopY+ZalbK86FfUgYhrm
w90oJnh7sH4YaIbJcqspX+7fKXKSDsob82LxxlYk7uSrRaRZuvtlQAfj4EhAO3wJQpHhfYi9dFg+
K6WgFYX3a14J6eHVLbSoriEOoV39X1DrrO5q0i4YzWbYLMIum0SdfRDMI0ttQrdFW/uCFNotyry0
zj/ha6uhhx6CdxRs4F6Zq4zkDTvgiS/UxB1F4IZi6FMu6A9w7Hi2eVg5nnxRtlVanDPi6ErYn0nB
AIH/wtwNIoCOiokkqIU7Aw0n+Y1/T/2pBXX0unC91g4YxqXxAxAAbZB20QctqSUhuuZYvvlETtrR
khUuGioe83ayP6BSeaLFQ7vhLlD85kOg1w77R/Wl65H/eQvBZfQ1gLepDH4hJn63pEe+5DWWg8o3
3J8N5hYfzGNwjCuVEp1jeNqnHh9StV7MYZ0j2BlPRa69WOIILdYNVHvC4/bSKDJRAtqXxEDrgsub
WlyRKefKGEgULPovSYU2hTnNHa76MTuemM94JHEkp0f8OLI81omKLf3jau0rPDP9TRI7ecC0gnlh
RTJ1Gq6vKShI+KWQs9XPmdptSIOxhsqUrcGrtfvfIAMFmI6k3Vzf4am8YtdKa8NRXngm3FHybcpj
sCDEBWBiYy7AcGTP+ZpPkIBuXssgjH4bNbPLgR+Qe0bYX5NyAl/1LtObsaG0mZaicr61HGZiQgfO
BS3DNoBrRvjiKhjMhkH9OTC0NNvFoUaYN97MCeDQYfv2CsHh8xaFaV/Xqyfk/JSIfRVRPwl6syPw
rUiPmHaLl31dAeFhoI8HYB6BPuE0RxhLWSj0vcFKsDLDbGeNGTuHMrKmbuEYmwjKjmbKIS/dSdr8
OFmbWdG2x3J/gLlbJUD7NXLtnLcCsUAv5zuUIUf3i1YazVBDCDd6xwJoos9/yFqcmhBxwMe1P0Uf
UOvNeJfQ5y5unaLCzZXegO9hpva8KirVsqCexUEig/toghvM2hICilWDVG2d3NX/kTf+ReIvmxs3
ysB34oHQJMEfB36Zlbhw/F+Xbr8xTDojn6V3Ywh++YGXqwNltIair+HxPMTV+6iggb3HWHnUZJRx
7nGnQ18IvbPUYYR+cDp2Z1EXMyfX2BsK7pSbn6KnTPd98qPPLVrO/HTeOiufJPUw71NXgNbP+MV1
SN4yRaBrzIDwCO4WCqKvMmNJINzDd0scwxaN53HVT8w07exwun8KJjWykmqEkrugbAKkRG2Gk7Lt
GnNZ9YBDsRYAy6L4XfN/NmzZXgH7SZ/haHPFYPYflRlmr0r5HBgzvNcgW9LAJIbgPTmSkamPW/VE
GT8G+d7RHTYxGqrRZt+lB1yzV/Fbz/eVe0hRzTd5ulumrBwO6impCzPAo7k3IULbI5VE0SC1LxRe
xJBUXRvFBzOU2DKwL6ZgXbazBtetngeOxf/25LBX/oTJzFM4PiviPP71r8jlO9yUBb23HZ0m6+Lo
psmAGqbo2s8TjwAWg6yWJIltAqEATnmp7weMRXHZo2jMiQYyeB+oTmX0vqzJ42/6Cp/ee093oFdL
bxOzETQUdu65kGS4HdwhQBNDyhrzc4vxoQ7KRkz6TzKR6v1sOl0gdy3vOvctpsEMGN5zbq2eCwke
Q+mT8a0aHMX+keAG+rh/3ggCzHEEvU7X35pFgo3HUryc35knz8SGw23YVOiMvdk+oqyVtp27qrk2
qXJbnQV2XfDUOWbFzuh++9vCUmRmOEpZipwcAjgoC9LRMcw9i628stlCpEjgg11NgcljRwbXeO2b
uggpx9VCYkAcn/j5QmtMAjTaykXjSd5FkZLfdrMJ05hqgzHIILjBYXctVNXDtYZpZb9dQtM4XHlj
jLTY9f9zgWwYrfbaJQDuKOyI06RYhySm2DSRiDJNOF2GG+gCxBUte5RmrOJsU3KhGn9SDr1UOh6v
f5Kbhp1n8lzNyp/mHVPg6Ion0iflo4OzKYzEjthe3fxGzIglx3dkjyrIuV+W+loNa4upHRjDAapr
zTkiIND/AjHuWv6cQSDvKbfQfK88xrNLRU0dyCH0+TkwuhdOqBP0SJAVBnFVWi1/LPLhcQ9kvsKk
AjoZH5WVKfX2pFomxRM3yRyhN+CvrslS5a+5cp6D6yeXMhLQ/EzuRNxCkfpealZlQ+EmE7ugsw63
sSAi5UfnC0RCZAEQB1ZxeI38zujXCpOwKF/QIBjTDm9ivEn0VLgJMZl/1TBVtIg6S17Ui/WFlfeD
CoHEGYmfGQRpnUuUQKQbh3DPSdS7OV495D28lJrynE/y0EqdbBZ9z1uiQiaaI9fjuyIr6BUjh58+
WXbR6GyVWX5426cIv38rWGSbBaepNBc1fRV2MRKzuJuSoBU6l5n6PkTeHC4x8X5bVoeYAJT8CtD/
ReCSokVGT2mFECp2eoUlIbWqFtnk3RAcIhJ/akKoo0KaZtSBsKTldWYyRGX775Ls0htI/R9laWEJ
hokGEA7hHFoIDTKtFPED2Qy75IyBr0mK3xM4rbYzdDk4XVXCfdO02voC67MOaJs+WbRo9/XJABDO
0lkJUweNWHRzH+xhLHeniniDFw2yG+uIQPC4s7x/TNygoB9nvAv/VD2o5eVaoKNDpeBC61etX/Pv
yggMOyw7vFX0Ir8h49lh7JCtjOeFczChN/LDykNdjkHN57ieLsROgjtlUGkvPtNVzQYv7fnVZ4PE
TxFOU7yTTVrVvrZcSWmMdMZKC7eAZOs70i4iL0JBs93gyqu2ZScoIH7wueJp6TTB7CM+UatA/V1W
e50ATeOLUTD8OQTilMqg/W59WWNB1vZ7wQyaJE1daxPbyDKLhSskQRRnx9lO8BKesITCEwtSIoNs
w/UvTujVZ3iLPiTESFt6pJ7T9XGBb2lS1bJxrpP0D1udsc/rDKFVqcQFHD2qWfdWbCgHTQ45lKue
oU04Qx5Jon43XSpUWM0UxSydJWodpD8Yk+iacGlQB8kDb6bFJeRgV0A2n12ADTs7Ofi8rr27aLsF
oWin8OYLkrffJKXVrFtPg1O3MH1CPefFz4g6oGt/o0riXjeG81SLLjLfSsQLGDPJc9PpFGG2arFB
n50M6AlE8zAkpBqYqWd5ciuF6Z7mdaJxiz3ajkmY/apjcjs9LY/RwWGHWppfPZggt3kauBQ//Plb
ptEjCE/W7MMLar5li1ZSYuADBL4t6DdAcJ7LmhZhaoYGKgMRcxBl59hahSBWXl0eGHnsXPteixRi
LBqVtL01CL/SbpokWDCozYPdK0OGIOijBa8OSHoPJmFHkQQrbHg+Iwff5+UQlVYD7VV3wa0oPFZL
aCwh5TVNZcG7UBhXUlcX98n0X58wnUz4lrUmTJ2KmAH2lfmt4dp5aK0rQ0Y3Sc04OYUjO10pK3SV
OrNUp6xKJPA+SI9rILyjd3399cfsmVtOZqiMknc5LW5mfuYCuNAAjZybqnTdUzY6MFBEBJ4uqj6V
PdM2GfFKAGGOHfFLp6XtDq1+BWeLv5r2dWWKDWUeG7rxiT23Dd3x725LwKudCo80Ts0BRmgw0H+L
oWCOfwXo2mKBVJQo10wSMc3glrADElWYEyPG21DGfyoyxXPtDWCFSzUy5cOtiVvSNsTAbSidy1/2
HqzS0w1YS9tEfkMeekvmngOIkTLY4I9wSnzi1o0eKNHCvwN/+TlbSiY0b9iwWHxcBEkjyZnVbR7W
Iz+V1zj+BSwLomelu0mwv5oZ02xDPcwczKvxcc1bRElqj1dHhjg1V/o74wHxiGWDyYupFfajSRLo
lonHsen0I7FRSmc8nwNwLuTiH96Tjwft0weNYq8RkFZHrSWKoVtxfeR5BBxM8efPNzPsuMVgGVJP
4cwtmI2KyrC4KqQ3KgDhkFz0CtofrTKqsXoAvB/T4pEmY+GVL7IgIlyTtPGFg5+G9ApTjnEcOXlu
/rsov2NHncEGj3YsR5O96Krm+hGJaH7y3whOJ284QfnjRYbOqJEW4BmjpRtl8cJDCnlINHT/UES6
r31UYoOMT847miqIdbu6NHMn2sVA85aflNPlLJwgiz2gl7ipV3J3qcEUpospWi0fuBtUUSJJ/OOR
MO4VZ2ayfk2SzyaLbVOzWTgS+Vy0yj0zs3zab5UM/Z22OSXVxhSOB1S+dGFhrkhxmA+kwS/fYHL4
AqtR2OZaUdf75yMQStK/R56vAOVmCLC7MID6bclGyUPhLBFXAvJb8YdUF/aRXIW/QUTpdpcXmpNa
gbO8b+V3i979kdeghhKfOy0szWH3SEQLW2hG0NDBTKSirKSw6ZrDBeLkkOnWZA2vRN2akCPteaSY
hkR2YTTZDVbjnZDimcGK/IFqMIWWrmIU6rULrnm+CxR48csot24PJp+ztY6FkiyZxp1AsFAhTrB6
AL58RIGGKBCUTHHy/37C2j3RU8EyovoxVZdc8i2ngVVccujbEd/Mjr0XFFejvmPAk37+O20+pGZY
T0Sz+iTL+4ds+KfOA+lR1VO93DVU0BiVFOlQsZHcw6FGzvJfR5GYeMHFKH9VGoqTjHfWT+ZHvr9/
ct8nf8jiv539tmpGfJwhB13ZqsX+62s7NL+czqXsDwHtIYYrCAh9ZTYavIHuaZAFnVdR33g2V0YM
INbT7aJ5dKDX7RQsOpcBLTGbn7U1keVtvjXdD6H9H9l1FwZPV+xRUR/4OIWllXIWeKlpnSfssilh
Tzxnk9nuzFUcLEIkq/f1s2HMiUbnskhGxfWYiQ17CVyYMvws+qgGtgAvCz3tEn/JweTrBhXNiKbs
zZ9DsfHrvWAd7PGZ17h3JLPPkS8qahbjnQSDMFFSPXL9Fj1iATnVwtBiDI63qlzkplf7qVeFWy/y
QgqzYZS+yobeb8vcgGPCo/qGS6TOQHD0bVAxE6NQpujbe+ayZydEdDP/HvIP5/850BiNAQMGDZMY
tTl4Ihnx8yt08EnX/shZi6GSVlIrdNApIs+x0cpREq3mnXNSKaODMOuyReiCbfYXIkVjDsrXSG04
Iaucoy+4tXI8sOLqU3tdlKOG/YO31/ljaHklgEfTdgitR/16/KR2Ld4BlsYXQy5Mw4HYjP5BdIdN
+g0+ffb0RQTBjY7mPP7kN0gGOuIGUT9j+FbeiiRibN2S28z/EPtYNb0uCIPC6n/HHwsPhy2vUoOg
j7R2bvMgnKtXVh0gZS2KONLUzADmIoJc1m2C/3MgICq1xlVrIL3+aPycsovhfNGSvBN7IksqdLlj
t9d5+qHYE5W/TqPbOn1W3WeSh9ab4wmk+oJjpW7qUOLBoaQS0IGof32B2dPGMn7AK1NBM9qO4qos
1zs9sHBX4zPrkDmQXOn1WHG3f9dgdjNhfpWL8mh0uBndr5ma+FIO5tUznrzTrIMB2fEz1/bsDB5e
G5+yLDVHw3gJE7Jkg20t1sREkvaq2nQyC83trzq4t2yuaSBz7SLqNZgv0zkRlDkwIeThS/6k/zeA
+5mj6OkljHgmJ48tzo5sVWBLp7f1xgbKHhPu/k4JqknlcEL7daj182SvOa4pCh8OEFrrxxeg5chB
cCvWop5CzXalDXh4J/AJo7M47Pfs5xftoSuuXYHDmXJB7oUrDx0ekkoVajNcgXOoBQGGhvz7Whxw
yaeTnvyHoho4sCz1Y2pU8+8lffU/s6nFAigYbTZUjdW07eeLoZ+a+6L2fgiEl8C7G2fLEVmQ/7v8
j9RSKBgwrDR00DcA8E1+Ynl4XY4/45dfBs9OPNQ7d6+Q/uM+ykJi+TvNItCsVz8tVbxoDkEd5K8y
Pl3Gu0pqySXkqSzturGe7om0r8wiORcifBotatf0BwnL9M74qx7e2aY+CXNGTJKbWzWzkQKVOLPm
uiWkAyFkSHxKkwe23SEK58z49yHcsi1Q2ibcQ5Nxwgn5esnUxdfrfainfDkxuRhdBWRRAz28Z9M2
s+K6zBEVJR50P08oo7Q/rMS0TlmnLlBwqJs3khltXDb5uHxaAtoXSZrQVPnwh6fiIYvbsXX3iOyH
Q5uDpps3qEGB67EWyOnlmXfUp/85HF8bGTdAmGOiacNKzYV7qeRI78tkXNKhLZWlnqg28MN5auF1
OE9uZhwHXeTO0qonf+2mR1aOsWRLHPgdAUEzto/GOelub6C9MrwFUHNPXaepsaHXrH/pYx+LRnc8
1lqGA9fx+rXFgdPU9cVfRJzdVQj7rbicjlv74F33qjpI43xBnJSwSjNvLwO9O6kEJr8Xgc8ULRV0
zH331Deeymw/M5b8st4Kq9wgFClL8BAWOyg6+cQ/J5GTHVIq4kD9cS/7xcfjvHsfbI/5WVB/eIeg
OUjPf3a7vFMffgV/ZsHohTX7yMlu1St780/oqnu107bFJ39xdjTFE77O2mG2GYTBkRVwTCXTZk3T
9yfGjgEYnzYPMIaonA24dr9NqwlDsuwRiqdosJlQRIEDwKqXHVA+s7kyfPP08dlP0lGrOMMD9NQC
quNpGv1Tw1xxShkeftZEQ9i7+GfBferA02+O5PuFm1I5u5YjNgLPkyOImpBYI9QmUEV7P98NDzdH
a+IThyzV0M82I2qC7KeOnhpN8xLYtqOsNAdHbtCX0zx2VTzdGYhadRTXh6StBuchRtkWoYamYSGY
3Lf6jD9MWY4eiJwV4S+2EBQ9rpT3t1KYssO/FMLDQN5KUA9Qi5TbdYSjlkozsc7ARXeub3Du7VIW
9M2cmK9aTdy+BpLrVMPKSeYXaZPdCsIDbgc0F/itfASEbSNA3Az487NOHHB1i/+VEcsWJY1HBKE9
1P2sx4xq0jx5wisiw8EgiS1JhdAVRrzBV80vxsQK/t6Aii4brF61UQg1/vwJMxmV/EZTH9OKUGoG
OumfWNy34ggrh04dwe5VZ5o6+7Gz2H3dyuXvhF9Tf2wwKSsQX5le3ZP0do+hTBn4d4ZlLKgU9Xbz
oqc/UFVGZCz0I5u698m7SAkT9DodPRXstdUVN37bMuWVZt0mLw9ORpLL4OOu5mcukQPth+KlR5rb
Y+4/dj2prCXQT5xUEanVszlvKYU7mIuBBIDPvnO5LrErNHSEvYJ3EiwKy1IlCMdQDfCvu4/QUDjz
R5FWBKcavZUFnaDudEqT2uMeCjcQTYSRg9cbyRPXyBA5W31gCx0npYN4G4s7kh35FFGBi3ZSd1ap
c2NP78tCd9YV/NgvowwlMaPAMAxyTJY3xJGIA5Cf2QE4HQhE0CtJLWn50yaPou37t37Ht8mUNHgP
gVc1hNbscMNZdTswhVAxfIv6kPZPWYOdUDGS+neeVenbZptmKN5goL/qKEm5tkcMDYimjZoBMNeX
Ys3W8E9V6olm3uBESYxfl+z33wqZ3cSGzXZWvwDpz+8i00Vxn14rU6mWqkP3ufaIb+YoeVelnj0m
STjRJAkOqrgQdaroARllCMySMv+S2c7KlS7caPj4n79ovsAg1x36cA7utj8A9d4gqs8mma0O/OFh
MuTbfo9fMAE4tvdHVadUSzuVdsxwYvuMhcU/rKB/CAjnqjBHyBbEZngJimN9DkRZe/XSjxPINIFi
pq1n2dtJOnfPAUwhxawuDqhALYmhiUNaDdlRkeDKkrpVVG8CZ3E3nOCu8gMTDStVAtpFSobYQr9M
Z9t80/22a3C42TUVkKOavkS9B8Qhi8hohzU9wm7BnPVYc8Ye6Zlr3lG04s8icm8+zx2kFfQYTjOx
sCxo8zvOV0Q6Yoi8jnKGQ2++ba4mSRA7zaV9bSfbSfMyAOy4sr/SbfbCVNjEs0yv0I9ul6aO3Sur
vVBKPeuS5ElrqCYaePqzIe4W3bK1e0IwGdGteiHWFJVNv73MwkAKLaD3Ej40lScuQ9qZ6fNFyx7S
J+pKq6h3nVZ5U3t6F0eWZ6Ul/eUHi8aSJdsGf+iUkHpto/cUxZsRbTkrt1tvKLJl9UMyE9JMHthK
p6F1HZBZUljLwvjKp9sFgqBtev4pyjwPaRdrOruvD4VRnjb3AM7mPP+R+V22rxt96Bnae+LBYpQH
LzfvuGMVJRny7xw+6HnKEuRgjmGXOsu88kLhCgP0LjY/2EOCaY19lyMxJ4oexOF6RuZeJI9Kp8M+
fT0QvLGRajwQSGPq2lCBRycsU1+8ISmQux7mNygHj/arqm1bZ13gboomXw0UkzgIw/T1WHnPrxlq
h+MNQVEifLqOldq431nWbXfDgzrr665FgsCtsrZWh37y3W5WSuEEcghKZ7SF9HsAfq947bn5J3WF
XJfvr26dzdMN5UMizcoejvycpNRCVLnAK4ClejBLCd4LS7A6/uXbQnrDcDPd5US2krn4qteyBqGJ
Mcdz8v4GfP/mxxvLPJHd4jIysTA5X01+H457dxazBakEe/jS68rKhmZomBBi77BQhmRMD5UVvZUY
dAfW09JPKCxBLmZ2RDsCkeRYm4AHayI/sfUhc6OrVUdBs49lqcZZNiXNic19ZoVHrIAlTJD2jvno
qjYwtMUEnuJvMp9+jbb09/YLNR+EuyNfjGk493HtECpzor32FcO1solyFng5pJLSbiK+5vV7TeE7
I7oTLCWJ6AZTtlF7nNJm4MFBFKtq4+bcnh00K0vAtp4Wwjk2GWv5JyB33pyBjfebi1uIowYtSAm3
eRCTyZ3ULCew3oePSJ3yDQQyMbWIPtTNiMtyirol6Q4+CGkfrs2klh6GNhU/TZS1NOz7mbDn8nhq
Un0zDWdROzUg6OtthVKk8GuFxGRzMXVBVmbspTE1rbgEHmRVYL4iiSYqJk9aiK+I3obeY7mkBDk6
T6qqVYLl6exO/NsF5zEAOMQFAN3muaGXQoy5xZ1Ig/dwF80kHJ9rDovIk+RZgBd/kyVPn2mWynqa
7CY5Jn0WwpW80aYgyR/BbHr/BCmFtTdBS3xwQRX/3sgl6npnleUoFdShQ4FE9crTuac+O6r6Jdgr
pQAQNi4eNR942pPHMDL9TZ78qiq10Br2Hw3VvML86wFn93ZABVpWvpcCtb0a9mnSv1wPrb9iLWdO
xLXZn2qqWQ5SukloksuRXed3DeEpr0AgyWNc9R0PEv7vmniRw/e0GobVV4q8FN4JkIDDW/ER5Yvi
EHMtFJeRWHTa/Z+h1awi+vmjMDo/YvNK7ZJfJSH/eluEi1x2egxt8a7eDOVjH6fhoiVqQpqegmfU
JZKJw10W+gUYg9tXk2vdLge5yBKltfE95qKLiKyoI0P3fQIcgOiSR4FizVxzhpHVs2uWd7OmvrVC
b+nJTDW58nlJJPtUqgnbI5J1nBayQxAd6wOXmcs9q4gZmaHDbZwHLlFHqPCadTuFeNtTJHzgINnc
z+ao+rTwBoK/Sw07qvbdBwbXz3dDHZv1pTIVJ4449BibA3xOH6FBxK/EKfHkJogyYAoOX2xt4mgr
ax7QLFleGlrGkvjhpLLz4j/zA9Tq/iNfU8MNDiGE4r3Eh+Vj+nSmrWcki9W1tyfl75O7slDlMxjf
gWZpvxup+DZTXbNPZQxO8gsqivcuKBGx58xZwTEK5cDDM9VmaxfLCDJ+QHMD9lVuHKYC7PTNcqKj
bpQvYvnh3/22zQkmOc3h2kgAu4OhgCiJaPq59ICtn/mxP4z0L7IuERPpCSPkvWbYLeNclXwEHxDH
777AmDU/CdgfE59gyQqUCG7yCZCi9+YnX3Q0bJ2O3yVXtg51zl0lsm4l12z9Tv5HSPdYRt3by4/7
4LnWYWXD9kuZj4+e1dz56Hl3zcsBdwTIW1TnY4cxYFM/dYvBkcoGr/gQCHoQMt7crMfPfcPupQwT
FAsF5WTRp+Ygm1e4Dxc3iIPBtUe0JqS/d0OKgAm4o4UiNW4tVSudlvsYtM+V9IRKYjbcvC/GCFq2
Vt5ayc5s8omRneMKbHMf0bydNturC5k5TCv5g4jCZU+Wj84aFkCoqlYd9xOIsnqgP6cAWsaFxE5G
CwWwpDbufH4G0iuL9xcSXRdlKz6L/0/cZqfPM6KX/TvF+8Y1DQbb8CvLS1+iCwU5SMupExrMZwlm
p7eg65tR6zLGugSUHPsaPvjctOduFfQBILGj5oaockpEOQGSo6WZ5/lqJtKeD731tkStD8KolsaH
MIl+xqpgSJ+6P8q8L6uBGKjhy1A6xNpWws+m6h82vR6Eobdlnn8bS/rxeOKb2WHCWlLL+qnZ50Q7
ZC8kwjhMVr7kFwvNzlbH1dpPwu36SEV7bFt581a03Dc3GgKaeS/97Dn90XjKlzj0snmvR6zP0HNQ
GL+gqGkOg9yAyVopX6Y5Bkz2sNDePNEW4OWn5jNHNqJdPstt6MObhVaiXgLGuSbBDBM1vEkyOTob
RUdSuYjgm7LSR8BrIDpQS8McFYYjrekkP8+ZDYdx5dCfRVLymjXnbS+7T8M9lJ/1WK9/5jnJJLOJ
dUxKKIMforgLGzrDl7vV6gSAKx8VQFqFRhM2SCfFSKvXmtm75ngLPKe+dTJZ6Dctzk5cskqXB5TM
gvD0Ng3Nk1RpnKyHW4MxB/pxnuxsLdELg+XDLi0ATw4LOAf9hhdK2UYGtJvtjLhiz1x+KaahBUf6
9jbTIMsekTMqsEaCwyDFQUim7k1pQJjldv0dOWy7LI4sb+YhJ5q2Wycte3vVUYOh0DHui/b/N4SZ
7fV98xSV+NhPm8fW6Gyab1ls97ZOvNwqJ2uJVsIJIlXqSvQVY9F70Ril83nBpIMcdscFNFoi8Exn
p2nqrGLC5UawfsxhRLZUhxIdylbqAyGujHM6WHK/pbSDg04bXAbgBtQfkE/3vYxDANN1AU+7Zs5u
hGTD8oyD4qXG2YYCH0djB9T0MBsvR0b+/vwC+0wXS7NG089yLoI1fliZjRaQxk++/rkkR+1KHZLd
bKimBHAAzaianmUyCwgBf6gOXGDU2poIv2gPpDzQrIPhsfpP5msQ9byvuroV3giXrEzpkD0OFoux
ydHgv2K6boKifOj9OZX91WipJ4Xo53rP6v8OzB7HVZtM8PSmDrTSrzkLsWPslKgE3LI0x94gXxUZ
iV8CVVC1HWkvpNdFDOtx/qOx0Z/PQgMr8/ouG+68PFs+P7mfyOEclZPNzHYCryGdowuWqZNEiti1
c8MyFDJalB/Gs8TW36omhcUNNU5HlQ3bKyMX/i5CC4Xfat/+3wbw8QOguWF7t5B3DpGbAJGplXzb
7WkZMzQSoI7PH06R1ZIZ00o5TwevcQW4ythrENPlUhXX0oYQbF1vt3i4gjva25LvwOVBce/1siCN
SkFGqeDd4FfuB4X/34Dl0BPyi0H8wFnjrmQ5gpUerHmyaV6aLs09Fkl04fGpxr7dnjZ5ZZ9j9nzE
WVI9d20t4xWNhiRrazyvnJK6bgYHwtGsTQFIN780Yczy3gupiikdFSv0TX3xE81UDvTDQPMpczvy
xVDlboaqcRs3MmrJye1G/QxWuhqHkYz0PSaaNu3F3NbHn7U7MANyIl27vCcZisJiZeVl6Z18sNAC
IscxfjnOIa6w4KzvNwHv6Jc5ekunZ931yIJIa079F9RwuScr2yu8Vp4drahXyWAf98pscBKG4V6M
u/vVa85XwlsbZQss5vTL6YD69SnDTdRMjTmhRAszFSO/N03RqK7jDnOz+c3TuVnRqNVQc8NA1y7O
r17irTnj2l65LvFVn6T2WhsaLl3u55t4Wn0FDrYBjUHokR2U+mguH+BukKyp7n5EFKXKSm4mhM5E
XX+n7BNMUAo50njGU0Utgbi6QwtWqSbz7ufhO4BYDISHyy0D7eeQUFXVxecotg+YacO4CQMdO35s
yzzzmu+J4kNk+c/fRh/+RtGL5zg3ozcqfIvNbmovkPANjuajZDI+8isks6DZuuAuBTKjLBZjcpEj
MBuiR3ahW7UB+LFYmIe1lWRP5hHbjEu+9aQzgnKS5XjUZN12E7EJjGc4IQqUAuCpL3qSPBIKX78A
fOQs/zxxBaAULfoXI59QWRKR1seQqMuvFVVNb7oWq+k8sozhSqqaKEp4AN3B8SAJBnC1Zsaj8LdH
zLvVjO+jfOp9apdVwYykEQ4NQqBEe+G4HloI6VxZUeTd9RNqsvinJWo2h/XiPgMAej1xt/l0UQa+
B1RAJsJ+AvRWJXd7SbXGmUXc2/hrDvN04PCL4Lc5zpZ0DR2yPihZdvx3DTKs9BtPcQ+U3sfMa2Zb
Cnmq/cqVulBwlfrW9DLa0KXqH0cewdtJm0sC7CXXRhZXXLlUPQTJ34kKfX5E1wYZ3gYnt9ioZ7dW
QU+YJpOX+Ciobq2yoSRniLpvfhyCaJ4F2jful1smWxAQsYhM5A7SXPFiDhhJCg9ITTs8MgpP29wV
xsmhvmHffCwHXm6Ikj+IWcQIJIAzHyo75gT7ZrsOc5EUxfZRhMS5DafOfImOwct1tN+gVPQ4/iKj
ybttPuSXCcGGpxok0IVOsClZ6+C51GgSjb89mAe0iGln6MVcSMt6HfMhGlbbNGqcbC8PldnS6e0D
bx3MVVpGJT/H38oY0wkUUD7RhTsIrUXGu3H/GeeMNA4AkpdEdKYNg/Q85JPhIGALEpUiXp2bHKSb
9e7aTozPV6r/IDoZCrSi54Av9hLVsIKwJtfgU7tT/RRusmVJR5ICTyC/HC1jjO6eTW+zzVm9YP0u
p388QdKqk35NJrkwqJMllEe48JTzWHycoTm15jAJHt+kzyZADTr8rFvg491aQSNL4MAqaxqgjQT9
JnCsjU6Gezr0Hd89O8h3nlPddTEO0EQdcV32GtjzJb9BqD9+894Xcb/Q4Wtg+S/Gnf02Zo9kCZ3O
wJr3OIRgZAFDe1RJjmYrhb3s+vcWS3wcODbwAKnnY8Mtew9xQHJZDujZmCvUK1y4H35Yz4sVLJJQ
Py/USYarCFzs3TJRktT5gEV4q9ZMNCc8/pm8Fuj2TPOxOKxCu9wE6vVwP/Uzj6/M/Xb8G125/r6k
QT5N+yX+vhFkvtmwiw/pBQZA4MTPNY7POXIg8iEK7Wyb81DiQOMQRvL7mxR4o88qeMBt6vhNRiRD
pumNtKWlCdPoltc+id8GlTvXAXQmvfk+xfkR8BC1YWrGmGsUsvcbUBoN6tGE+hxgQjxpx4Li4ydZ
yLiV/otfekvQOQm9JyBuNa8E37bBlMGt2nwmw0m3MSD04ZUp2rsgE3zqKxuKvuV4kLrkm4IeSEdo
zdoWcBDkOOLs0PRSIAugtaNCwO+S40OFBbZtrr72BlHyLs795mQyR9ZXqSj6fe4iKrll5mWK9/KG
V2nKgbZDI2y3AIM3AWrwtFAOJr3jXHl1vvVivj2TrbJLiDpAluuc3wV+wVYpPg0SqPNR1wcK3Alk
Vu4uiN7s6zk8n9tYNWc1e/Q4txb3s7IQMRwwOv7lytvn/roxcn2Vsmx9/T2JZU1LE+dpC7up3IF+
4rQ7vrxRbJBIBR8kCncwm8mmPNKFNFNqhz9ohMsNL6aqToXmFmFkyg6+UqfAqlmvOemROC9MaSfh
ofPLZ5xF7qW41hW13js/3n5WQvzMGXS8qTcvs66mfn5px5mOzpW7ApIrDDdVQ16WbOCvdtvXj+iE
oR0FMHYsDlIfAwfnrg/bKOSvD87p1HUjYxply1BRWZWqhNxeoIShOcLf9XcBr/WK1QXFeL1O2Zlo
+eRaP9NXK3Nmgp/iaZDjsshosMBaP/tIdGaHAT6arO+CcVngESWJ4E964CfnOGMYU81fjmwgAkeF
0Kcxqt2D/q5cz9Ja4Ei/urw1oIdGCtbMMjKkTeDS9HKslCbOnvfNSU1OHl99lAop8HEkJLAomv5K
XZPyz4iHRGblj45AJsuVJQ12RqJWGIPR1U5N7N7PSkjSCYhUmguK0OW9dmpaJpZ0sLYPIugzMHeT
KEyILxqiITObNpaq7Tam4XKRn3kgNVaPciBvUWW8DQTAwkGp0n9Qf26RHoK7ZQfhlEXu9bw5hhqM
Ormee6VJ7p71WNPaUCnZ8B6IsWeXsDiJRzjhXQJE/5xYUzkw5kZpzRAKL2BlBOaIjhvrzJhtrBFT
dNSMXOypZKPl5VVJ0kIBXtDi+JTvULsfp4uXbZB4xuXRTZkHOc4rS3jf2JJatLEViI3Ysln1JKv4
0IBufVTE//e+ESIXoiKa9Qy4NZhQZ4cWuYQ7qZnKU5IpW+XxWIBKWuY0js2fyaRlvl6Q5lMYfUyj
N5kFUIQpOAetYF1SjTHhkvE0i3XdZf6QdI4R/7wKnffFnpNnGRB9GSIb9aQN5c3rwRTmSS+TfTcs
a2RjkB1aekLAKAlMjQ4Qd9ocBIo+KWx8QSCkys+XOmkJKrswiu384yk5JEsHhVhBx9J85meW/LsW
sSpY3flHfZKkw72yFnDecOOerMTB/znxOwE0ml1ja2aRM2siPKMqyQKTyMLA2z0ddqsnabWjvOAQ
WHAOwqlhjU/jnTtuBupQQGPQ5kbATyqLRPv/8Xo7g1ACsuuVUmaKLQyLo0ckLWqkw59rYSt21x8C
vddFyMS9DvJEODS5pLGz7sM7jRXwncSfIwQMh6W8/a3tOQc7V41LW7cjndwVGWVQRpM24olcfsV2
PLSHI4g2RrRaxlW/u0Zc5+N7CsIWBI8YIv81MfYH5PmAZ+9NHKC/moDndqHmplWsh+UwJidHdexu
hC6qhJl+sTEH1nWaSQqINUz7vlDcO7AvIWlUTexS/5cpHuaSejCKkQP0NvJuBlO8FNMD30VHnhAE
/90F7tImQxhJu3YjNMmcOLMSHcwTeJQwWC9YodddUnodTBBt8cIKDkFohNBpYANuP+4vVd4XTZGm
oB9NGEhvV4gfLi1WADTOe8UuAWbaAgJOI8gxqZ/LD+Fhj3oB/lrEbbIi3Utb3D50BFgj9ZdhZg6h
YlQbrdeztwR3EuodxXrOFWDgE5vcY4ea0C3ViBGXGjNuJV53IUcLlmpoePJLejB7nxMSNzpBE6gX
XFccz3UMuixxjbpzpP2zf7RuK0e2rkCVgxomVS28C3Wbbx988TNtaZrU3rjupcq2u19i6Ul2eLbZ
CGDzWZ5637tZJKyapJ8jvg23EFvUkENvLcPK+xi5a4VzADCMLk41GIx8DUT6myWlFs6M4kdoMlOK
wQxrr0+xUKFlkb3Lh64FIytbnxWX7CPV77WHjred6b1a+fxeJG5WK1DES679/NDd8YihoGbtUrsh
JVpzZWWOYuQLdfKiF+ZLemK9GkAzEjAwa4I8fgME0rl75Y8aWTn2hofEfad/FDa6+FKm597otgwd
5JDOdDzKLlH7V92shAjITPFogDnpyFtGxV9soJFc1yVjOh7AY0kMlTEA9VX6klVNb9t8fvXYtO1v
mtW8BLs1MrDFZa6i7ZjIvfAsd34H+yRjH39e5EDYOmhN7fCYtJE05HVaneS0OKJNYiEaT76QSWgZ
fLZEVpL8HXBZeZ0BO9DFfIImSZRyQTEwqnsguhXoJqtaL9Utasx3rCqCcwRSi9Un5GG3RVbk+cGj
PgknX8BqGB8AY4PR5PT2NalYVDMD4vVvmJlVgw+VA3HngtwtzF8I2mnF0W8K6IytquPOhW1AWs8y
XJwzBkU/0MP1Hx3zpNr4/Z2kozUr8urOco6bHIZbGQyHfnjk2Oiy/h7kLZ5zB1X7rcuhmAvaqjYv
dWVbpWUjsXUbvIDoKzj/Ab6Z4eGFkCxVFtwA+jeWFMfe2mybZxWpLx7IOFsnng/50Ui/HkLovJb9
HB3lRIU+TzUfKG0+8yWVppA535b4f/W2DfrkHDfXRLiWUS8UkPm338udz2FSsj6GW4Wyj4mLarnk
3TO4JlAKjO+yctrdtN7t3YEjKN6wP+8WTpp40Je5zkH8qnEhUzXPCLoXhpZ9cVZJzjwpWkw7QC9p
YmmyvsWVed2zTc8tYSlxefwAaWfGwQ5BSaFuEfunGV4ILUJjjfmDbJ3b74EAmK/yYQNXmXlGt0ut
LMBCnpkb8awTFEHALUbB0xddRRlYvHM7+WQuiDqkdDAb/6v91RjsFQoLTZtCufzCJgcN9pkL0kof
qDwJKYz5zJz8gdZK1ecU+GZiVAkFr6Ha0vgvNUYHfT1HDNGBrNvW7eu+9WLFVtTIkAVZL8KXPz31
lM/TZgQHZzkqhpjpY4YCaKUEtrJ4MYiYbrDMtbZspgjzmgdscEC12y4q37k5qZTBwJFssFBRxiQ6
o8RQze8dEnStBFTA0uhPIO2d/MbDzbo1Pg86DomHrldAaivoq331OQY8uK+xj2RGrGdaVsrwu1hq
KYvMUuN5nLcGZwuIqrbPfO/hSTj9dV6agw6ILw/OeImSwfYkCI7L03mdwJGZlO1+xk5DJfIW6At1
GtGwzgNS5T2MHWCQMgL5nLSxsldoBWd4hUHW6x1XYeZMctEVIoWvqSYMyjdGzPQKUrvOFThHD5rd
DH72BITx+X2D/VcwLjVran6TuqGZO6+fsn6stCcBGhAk1zd2FvkG/zlOnw9YDAm5BBPIvNkN+/Zz
Y2q6KdHAQBoLBlUGMsOMVzoDo+ErLabn0nT+V7uc517Ri48ylCYROTmSZIG+Jcn4low/GaX+rzIQ
wCfKtatxN0spbsn4fTEp9BIdSJHR7cj8guxb0JzqKbEgQqiwEhKgVghwjL3yOux7CSCqdyGOOHIT
61Jf3qFshDmMr9jH2JXZImw/cnz4KPXXKaVPBD7UviI+yoBj7UMHSorScG3WbeJONbep+N4h8X6U
l7xU9Z38327k9QdbQ7c42chp8+qeWtJJbSZWc1tzjAMCRdzfElEYCNVCnQHYFmiml+apHJL0WgMU
Jf4AByjRJWTDUUblldREWDJNToZK2w5mhR9DJyfV4XL0PqHmkySqzro0tWf7zsGhTiPOCwqsHDno
0jtkx80NyspektQZFTB+/Usallu08nGHLOWtM4rbFfcWKNO7Dw3RxIEC37bsqwn0m5C+KQrsWS5m
bA6rj7QBKpkAEvsOd3QEaWc5Pr41MEF5VHsfMiLqBhTnXAFr65+g9ptKym2NlB9zU3dtZV33/vIO
xLx6un3ZgPAeXyQgRlxCWXz08GqSzYIqoStdHS4ferfPPYlL91xRSnOO/+Lhz0eymm+/mCdxnBHz
d2h7G6DbhmeT6HcIaRYb4qfVyhYZ3jcZky/KSReKw9SD3B6PkNfw3gHlIPgTqwtK/INCQKL7MWoT
5ad5Srktvau1YhvsyZHAut6+YVCvLNyMdUnj0O9dK60AgqfWZ8bfga+vnZGAF1bs1aZwENDw3l9p
zpu+4TCbRmWFDo7C+CtSpKAgSUTynYbWeWI6R68sJgN2m6IgNkNzekyzURuqTW8FqEAaEWZzAo0z
NHZkJRXDQR8KVELmoSQ28t/dzibq0UK86SVrnUvAzbEhQbbXGxBTFgGR76JJNcqgbz9HSgAozuyE
LXYK8JaNwq6mMYgqxQQ2fZiXIuAP34Ez3Kypj7war63Qb+XFCLQfjtsh81OkNcUZiehQV6LlRiIe
vAAfw4KjDpYMFqc2iDppHKaYYqL4zAJJbFO1NYu/lZ/HGVjPVJIuTVvbZeNut8FddA/Bu3bO7N+z
Iuo11Fxi1S0A3rY2a8x0mzlog+ztkWKLeyGOcdEBuYufq4MYGJAF7ZfTyxnnqWujXVyH/erQ2vWk
8E5Ha6i1d7WrFPpOd8mrz4rS7Ve/exuOK7rVB1mNJoF7tjSjNBhQFfGfdlFiQ2y1FVsvGB2axOCK
MKpyYadlKHUc24yQAruyWpOUQWCe5rNBrAASv5KGYJHTpKMXvOpyuMh1SGMAyrIWdRIEGXbjiiPv
lIKH3F52GMOFzlArrFuaav9ydliqHrqVLGDVLs/CYQbEaw5pNIV3oqKcIrQY2M+OM517464I5p6g
dqlZyi7Uiw8RMJUSSBtmcGj+5Mz2O27PQpNDzGiuRIXJGY0wupVNTSMWMw0k4g5s68OuM+H3EJH6
BXurvMUqdq7n0jxL9vAES1dcShOqCLDGBBW/0V7NaM+4O8G87IgIYHmvZhy2/DR8XcNfxu662PkY
DAlOH9/pTPoGPt+5LMIhoCHFkp74pCvWBTYlS4R45W3tiKQ/6qhiWBhroFS2XS04XP5fAONbcz+a
LTJmxlwHYvudoiQ/1f42ih+8uyLnvT4g2f8gEqC+hg9sAodtcYqsuRUhg66JLYE/tCb8nD6tyZJa
8mYSmjELb6wh5XxBJwK1ZDVD7Qd2gBAxk5IoAV+apO/wOLCJBIuIClOrI1syFekFTRtUK7ESdW/S
5slqqpNhZVhjz/jNwR459B8urHrVuPSALJgM1N2vMxWCZ69PVmNOTTVizHIWUJa64IuZLej9/kyY
mLZxZQd+XbrYl2/ZetSXfHaY8iF9Ui9PM9tYl6ybhFCSlq+/p9RKb5pa2F6EhIVSE9ie5aghUhbw
hA2bkX6lrpbq50TX/9nJQGGOHulidSVSMdHzBAI6lpI8nLfW0jDjBUMkJAvCDKGit0LIEIHOYOIq
6RbfwlQbYiEp/BfxqEImYf6x3lCb3Q+umRexk2MNX69E3tGjluoiBl3/ARt4l+0mCr/bEH1wvdrZ
xy+rEGnamouR//Bq/wMV7+zL0vXIxv4nGLUCywdwYR9cvWrg1mbLiSBgXpweKEfYVOARDqwIambd
OaL5WsbVBpX3sxrmR7cH6oJo7qbSRxjMzej97tT44nBrfAHvk/UgrbkPhAZMs43Lz1tGgqq6C1N0
m2W0Xso8yt1Ld/+S0zpXk9liWpcQrAsTcNdHZa3sy+xi97/3LbBmsMuBzNR3MmMxya3jKm75aS81
ffz10miqYvvRIOu597tlxJz/aVD+r6SdxCPoMS36u1QMxqswPoExvxyPkyLww+SzUPwpv4UXp6mF
j5m2Y9Q3CgjOipRl2PmnMVw87moO1ept9nnFWwoTZKbXZhRR7TmmW8/WrBbQUW/mEcsk6ARt6L6i
mvGpKhaIGw+uPWxb9VxqW75oeOUApF/TGMIJvNqTvpoXdExiQFy5Ux/aDLpQP3aOSnY8CW1v29zv
mjifBwKX9EbqGH3ug83o/meIJQGcQhB2JzmdXYUNwAKETZhQpStNBRhwumc7zUTNTlZsOlD40DA4
s1uE8iPhx0QWdE+XK9pEXUHQK9xtBsyn+9FJ8DM6LcT6UAAe1ww0709W4H6Grzh3rDP3bZZB3s0z
kJxsQH12XhUtcVmgKjIWftzPE/GimW+uS9OH7++DJur4Ohx2MgmeJdPVfLFFkLxZvZ7NYYrU3dIo
2Qj4sAMhZriq+lUKtV6pC/t3AMQqFArxNCiENF9nojtKUJVDdbG8WwhzRpIytCcmIwlTKB6CY3qS
3olKiEHOKacSa5PqrX+3BAi82jHOrvgnnSsC89mqh2ZS8a3tcUVXSeBWZFu+9MdbHG7MUztXMCll
vQ3zGdIL1RJ4McQ+PMxqjug/mg2MRHA9aXoMHZqetGJb7m10gUcRGvW/DWOTNZDX/DXkPksYLXkC
6v37UPQshfY4lOHVLa4YT12Vgo4PhxfNDJWqjoDap/+GEL+hAerFaKZ9JoEfnZC8DTZpw+zbhArw
tS5hsVWZ4K61Y3Y3FjqwGtuWVfeY1gr9QH0r0uUx5ysAJG335tV7jdSSrtN7xAYl+e8FaiYP6mx2
zMlGqcAgjd8EgT5y4TlKs08ilj68J5mhEif1KmmJWO1/nyEHxX4dQS/EA9c5uvCCyDR+d7lBu+6t
ZZBn1pGXe+bRBWaPqIEd/9rClSGP6fi6OsFX/CILaUJc4nzewO+Yc3VjqrBbOJrRhG8rnLmutcyq
5ebtSgb4UOoYwEklzVKHC99mpAa6kCmkf4sQkoYgCB3pCAjxtTIsnvev77m7Uq6nouYJ3mwsVMlg
nEnvDXmE30DLjhV6keDp7v/4wKUIa9T03PLxADqWC4xrgbRZr3cxHxbUhHegmyByAOP/MsbK2Qpv
emz69Kd7YKC1PfWES7Y6O3rKXVqvMeR/1DcSdlU694GXLHpnJgl6On4xeAzwGfG5k/KvnTjKIniJ
whPti8D3LotgYan1Sr9hbyC+6c8LYN5IEWixwVMnOTY0GAq4dnXIYBQLaCZCiUTSn5zNJPbi6EGx
Q+PcyDVlrqgE9vwRP7RTX7+SbUy95PZbH4yfmSHgZecUjWKwU4XOe78Jo1sT82avVuf4DI+IDKrk
J3AW9i0r/u4b/spwd+CQ/UuXPsllt+JJ47kcAk35rIb3jEF2mC+b7dESLlScZDJjeLN9Bw0uAEgZ
76jPj13DFjSUb+0emb5vf5/L/MERHgGXSpzxMKx/KV12RmjWh96XtU9SNMbxdjiMasQ2swglaG0A
GdYgntAbdjRXqs2ZNCAHfgwoUhDkUU3fuIgtRkdcPgy7CLJGHC4ssgZv5urpLpmYnQHeYuYgVLiE
3rDIIn5Pn50ZoJRQ0BnMbqjIhlDhswSK9EkuW7GUvzyC4vgPlrjgsLAyZihrVL5ocDRlVAzNjBRA
h16WrpSO3nn5WWm26C6CLk8LWX1vTl8yHozMNLjgrAr6HKL7ZTbBvMNlglohJ0kgQ1iOO/N8vJBx
huS5Y+8fw+TvDSbLikDT2LivPX5tRejRbSdDsmLQf/MVD3ezeG2xI0qWqnUIpXdkXPLQlDB869pk
LnFNhSvaVETt6tp2vPh9u5ARKBYFNv5NYvpZUgRrjSdfIJRbDOechK1BDAIFCheWnndD2F28W4PH
8PJzpyAafGjPlfsWGQnXWl7x5jleyIv5+fCjoZJhGfNP9LAwguO6ZTCkVosPtryZfrLjWueeEVW1
67OPkZ6I6/WSD7nKgK6OqCuVVf3ijgjBhcSF3OlafS6mpqKufjs45oGFcMdvU8OA+wfcjxkQlbQV
NgeSkGc12vnWFWIyppUDzBHZBSfuu1NNi+QIFHTLgjUDYz2GoY1UfxNUp7YHZLceq6yVQmxXCg6a
vCcu7taLQobFycHe6njPWtvgQC9dU4fEhnvdbiDQGX1ys6qxqtk0eCXu1qJhpPjXfOJn1gLgDbcD
f+hP47xCsacwdOkGMlhqjKsGxezRIg+hK2UX5DCa9vlIgiVSJVdzj5e/eXLFhA1xzH9SUGV2i+QV
k3ZfZBF1ZUwmiTtb6eDKLRYA/08ltIGhLdS7GPaEWej3S70E01RNm2NEZ2CneQEArUaEve2/f0SE
164MuLWRldGBD9KANaQt5ZZcCgIJ5QH4eSnfkd7n8wO1AnZmdvTF1CUq0A2Ywh5s8PxN7T67EY86
hEJqChq6TUtBT76/XTCHr1Le1oHX8fFzugcNXcwx52IPmeMJjVTQKiEnmy5YPvCJFSuvVTj7ak7g
0Ec0RGx1/vqsnXhqrPn/dV/ablbpX7VIk8rJ6THXMYK60AvL5uYd27bdZs+ox+qiEzQwtT/qwjap
4sxXwO8gyHOwKh44gQh83TKpPzE1LJi+Kd35Vwxy4Hkbp5IMdCDIgq8ye2ZsrB/ha365hxeOkYQI
27EkzeMLhnp3DIYQCUa8jWt5KtH8gpKEyyEiz/1oYPKLt2U4DSglbsPUIXV9w61erqAl9+ZScahO
6WD/OL5fmLidpu+Q7UYe8P0ECfhjvZFEqSWGI2he/qcxb4D/+rYE7OZ8xw7CUSlxWGfDaR/CqgFJ
4ZbVI1nCO58SjvTIWHclp+s8TgQqVhG5iCsejtv9Srik9iMENe7gnMRfeXJWaUdxDk9Ey5Wz5QIU
kZqmoUyUYY5Xv6Hc8DpdELNjWqaXMJDPXl+J6OuC/YdfvJy5x72QD7Sh2yHUDG6hO1iAozWrIeiB
6wJRA+9WREVO6KhVDKAQBeN88pB/eoWIAN+mim6cWSuCkEf5UgohQZGzfuU/eZ7kQzUJjY5eIKRy
ysvA6JquQe5A3StIIlb44o2RV5LEijQL1RmwSc3x8EcwNL/gbC3jIXrYzhyNs3zkPEX1tJlkOQaV
Fsw1sHmm8Ni8xVghgZyB5HbgIRxavExVMAVUItUC660Ga6hqQZSxz+IR6/Wwts2ISILavBd4iXso
21aDrOhr/CbCg8l5EZaoPuXykIDTUryo0jmnCiI0Zh2yTLfFH9CyQKN1qtjQVOqxODLJLiIlRrb2
ce/JFyspLhHfnvmIz6Xt8M5+oJ0lsmMeqRBu+K+Mvqwt9q1Ipm94rdM+pyPhG91B5DBCzBoy10cC
EqJOAnY4a7K40ovAEsr/xabYnaW75nXVdum4fLG2lx20yEwugSlHnfvs6OcvznLflwzHvZqsSBHq
TSo5x4QnYne7SenPIONPC2b/9x6U8eQgxvnjVPv3H9KIkTczveDKBDU0NNNCOOHxsFDy6PEXgVfN
E+kImInh3U5O/zDGJkxXwPijZkyeUbalkZZsWMoW+3w+4GiWOPmdivhJcT/tl/v8J9Rh9ZPlwr2/
dSZc8SVGNP+r40vJ23/ZY9+Wo0W42ZtOR3EDBkH7wrL62ShbVQAcyVYlaS7lgvFPMJJ3xB2a343S
Hq1KKGQYc1GokRLk8EkbqgZPlI3wBAf1xp8+gisfq0sfOOmiaBmyGI4Inamx/vD3uBHjS2mlVHIH
jRsHIW5PlxnIg2MSi0jdrqM8PhTYa+SFEh+VuNhziJXFYz0NoaSeTrr832z7dmjj6IEP7Srv0qQL
UkMNijySx9Ws9RM2IsP4giiL8ArZ6QQTf9fGmEvvYNBtoFtXE82flbYLQNFRp6axpHPDu8T5vA/Y
hzJlE9w1sTF9U1bXLXoNHlwWpAOl/8pPOhGMtp5E9bGbunzwXttiqL5/yAnhjwVlWvLZxxDBj5MM
ASDC+YGJ/s642wYCBd33i0tA8ZgbTbhn0fQUq7d3wmk7RjVzgVjzg9CuXh+6F4VKMvi5R4fUbxbG
qc4en53LF75qgpiGUM5PmZOum1HjAAz+WNoOAgzRVKdp2bPEMbrpm9uIuhcObp+Ivk/43Z555a/J
2oU1+Vbr8x3Uo89JPO7LBCckFVjtqKiD9/B/Bn64tMJZeTVfV+RYqIaCYSq5Uo1zh3tO5xcdnRRU
zuU+/cX3O8wFxw4smOazv7PvftqLiRdsxQqTYd0ww+kNNAZoT98pZLGALgwwwV8qp2eB5pj6eP22
d3NW/cFekw/bOYjfAqzjrdEz/R86S9pkeAyu8UVcBob+uffCdovR/V5mvCIgTNxPLQTfzu2uMLLl
ALB0lP7S2nBtcrMK2xLQE4ab/equqA2gJeGdD6GjHnR7Q4d9kXBRxBEkbURyrphKj7ciqnlemDWG
Aob6wFjOKIKPnWDUcr9P+ysKHhGA8pktc0eklhZpzF3ljMk0bApt5onvOlNDTvbVO89/Gk7sl1pn
ai1+b+C43FfEvoFDEdHwYq8I6HIuE3SPZgSz4P6Mn6/H85YyYNZ9msfzWzWL1Cr7RYYbTKMunAnh
PBew4ZPbVc+yl4jAMjOQxlyYJUwARQ+jNjbnt8fUqgv/PMpEeBH2hJ7kTfarHjWPLkSKmR6m3AIs
+s5xeQWsin80SDviJI+u3XCgYQXttXUZNM3SUZZ3EAYNhWmCspryVAwiFFxhaEzO5xKgPglhVyI1
Y6bVSRUHuQJsaxXcOhg0R8OWiqPbftRVNlsNc3cUCr3Ps//mzVzvP/voI92TidfJiWCwwwree/ru
U/VRtYeHIsC+hOXmUhhjpuZVg7Bl5f7D91o8wNzGgVMg1wGqenyjt3Y8faOqBLWf/feYWp6s3jD0
vQCl/Ouw3axCKs4PQCvAVO93FKoRwNCZkDRtdFizJpO4Nk7wsnX+H0PP1o5lVMR/anIDdHCj61Vz
cYJPzQ/SDJeNj3MhV3wxa2IFPmKqFKuPohA4p3omlA+XXKbf68y1wh5SJpxJjfpwuoE4FbvZTwYT
nxpxmApG0gi8T3qdDVWTlP8YZESnXdt3rv0qRtZnaJVM1taHd2r+VOy98/ODt70w5GM6VCs6OjoI
0nd8BiDksbEMdwqJWpSd7pHDHq/3Mswx61QdxqgovvisbPnaVhdZeT3vQm9XY0QUvcfA+z5ll+aM
r7WTGD7Mynku2POPNynTj7Ypvj6U5pd5f1vWvXoBsdx64EgO8uFLvEZy4H6mA3O6DNV4Vm7OzimR
I1leOt9Y7sDGHYVCT6+0HcA7TpmbXc39N11MxVT7ij2R08KMMEfZ9U08SIz5Wq1v53ilrW+1bx/U
3JweEtRo0TpH7KlD38DwdAOfDoHOx7IbHoMXnlqKHkfPWIQWnvbMONkAJzc1smMlnB/RYDHQnwdi
PM9KUCIto9++rdunQuzZLfTATGZBlq0ZcDKbLahIg4SA7FObsfImNEwu6QRfHSTPseJG/jjr1JBH
nyqeHGzqBap/9B2PrHKtBoTzcmSljZ8cAecbqBfzYOtecs7eLsdtB1cJJM2pxF88y5L/kgnCNGMt
h1tNFNlIknGbW+QghMTTPXUTTJp6V3jxRFx3+M62vIRSloNbxdm1I7eOlKljrSV1zmT/oQn0ekG3
whBTqQ9x64F1HAiDR/aSYAWwc6BoIYmC9cL68SUD0/1sg3lpEe0G1Iek581iWCGyFE/UNmwbumGg
7Yk6+8H/jImrgUCieune2+tXRmp6HAobXhXei2V0t7net0Oa8XEutTJPRWa6mAwJaGD8MxDh4qh9
u/EbS48k/t94wqjPpcH/W7u1y4SITq3rkCLg5SbnSC2GNQ7voiV3k/GbbO6Giz5JWYesd5vz2r43
B6l3ayFUeqEXtTEvsmfs7Mrr3yiAut236tWLXez2Hb3R0Kue/iHSsvNeaRNHnPYuViyqXu0NvKJ4
eHb7fOc7T3qLikGdGUcQ/c+G5Q2YRl8bBO5istcrILc5eDdq3B8QlNyHuPkokzbk+kARD0nCCEZl
XDHsGuztNXNz7G61ptyJMdX1L63bTih2ZPX6kOZPNa4OOW7Ol98GGmpCpT0xp74h3GVlTei9vUzA
iUZBgb0Zq0Bb6MNwjiPE8Hb5t4sKD7Froc0YsPP0Hm5zDy4wL7V7L+ZL4Uyf9+pwgUTKEReuSdBu
qrIlYwONWVPOTRwfeTPDzbfgvmsFv0ro3b9ZDtLcT/cxePwkIhTr6N8p8aoLFHeXmWXAVndNGNjU
t1yKDuqd9qN+4EN0Efv7k9tqohwgFavFX+bCjX3UgMnulZmhUDihBXHS1dmTCk86jiYuWDyNSleP
HZT6AMK/OFR6sdKU+Ql4B+3YnfMsVgm/zlrixJmbORCGF5ECqASUv4OP4Y82v7pSwNJm6NZgvqdC
tqnJb17JArBLDhD0ib7gsSxOdlBY/HeoPF/Ma/MGkaidf+KV+AKqylyZw1PKCJILWdF4ZRmaPKev
N7A1XiteRWUWVFV7is7+dFv27A/FsFqlfvKwVN1lKwbD4ZfUHnIcGUR/XZtkvFNSuKdDCUIufTXf
eFMRCzViBIkTfhwtGgEBIo4NAJ071MOhmlVkGCTL+EfJtEeWPZjFlEXACCbFQjLwdtu4RTP58eck
cs+mDi8oJn9v8YCUIAv5WFfWZAsiwT5W8FLzDraQVHt85fvmceezxjqCGntLr7HBOHqm5gVthjKl
mK2g5Mx7BGZ4k/UJBvkUV0gs5vta+KRWayaxr389QtIVrpxAbUSlTbUr8ldYX+5e2EiGpYgUZMyd
hwSL2ZjlRr5pjMEyaDEPHecqTNaC4XSggB0SUB/yyjt3dHERbedLif03syPi3h+2910oj7e/OQxP
fREZgwPwZ160WK1XDtRJ6r33/AW0TkDI36X2ftqtQdrx/hld+teeMQ3FjcocH8qchgp83HRIC9HH
JThmfH+iHJTDD+D45hVVtFAo9qqxGfoSWQNu85bVO6jLT/S3nVsD1RJakX863TQzHUECGPHONtIC
prV8TwxzIwWmkuNSGD79xIwMB5kkWD+Fnc14FZxHgQuJtbBjQfHpMnfnHwhdcYlSmhfqFgrBqNh/
i5t/zx5URsGgSrJcqJRx9KM5VxKVD4SU4Mt1yg0nZwywsplVPgu6KUZql1jL55YqsV8/5IDxdnKf
DSFItb6RQoB3V6vmagNx+DItvpUWKZLQckrzPaak5Q3fR+I6z29kIvozXs80R+ox6cJi+XONT2br
rbdddxBg4OiLGiyHjgeSMKpokOrmOiR6dp4wlDLeSvIY7Jx7W8O1wydoQ12M8PiQXcAfGeFkoHkQ
LSbiWIRKY5ArVgjSzRp39ZrGYTtfM+Dq6LpO+c1so6xKl38IqgqOzAsEH3kwq+YrW/tx3EJaqKLb
r/6z8BPgjyP4MHoluuyy6YQQGTwsdqSsYBx5Ib9oc7I+blFwZl2nS7ayYgSiEpP17cXT0NHGEWu6
EUrI5n4uXLr8hqYldDYipxYO/CXk6dZ0/GWBefGho7DGzq+ihSl15/daSmG5a4qKTQDxKT4Yk9Go
CVPYgQaJzVvRFAsOIlxe+ZdhVS3iudMtYVPIaYJjC0DVk+ylFwRs7SRKhr2RuKONnU+pcbar+cNl
jdPo8TOnkMCSrFR3vL8+T6WfA6SbZBA2VH6iIEJuySkQg5VdghVrLrgz+dGdB5fivu0evRIADpln
Wpm3Aj5YfEWiy2ObwuH1CR/hdZUDQC6tI5bLXgbDvJxaET72r7VOjJJKZj357XJhEw5RMeXaB7vU
G4HXBe72zrhibmofoXAPM5XpJaL37j5l6AnaYJavBARU1mPE/Bg3zLEG1R1yEJFyYBGIoaYFeoB4
qFD1OpDz6s3kPewqM3lO5iDHnxymM+oVFr0Z2MV10tLGoEM2iN/41/DchumKlrukenaxG/vwZ0kM
5HnvdKHLGTzOHvTjwr9U54SGjvaflg4i51M6ujwd2iZZgraFlgf4tO770eTifcyaSqv3bJJTTn+P
DW5Ay55PRpdDjc1V7HEBPffnL5kHa5LEk+W9NAYSTEK+nvDSmILVyFFL/SsDtdkI7JuwModcE8J3
le6qZxoPVVPtVEmFh4dLF7hh/Ai4/YiyjOF/Ye97HsQwxJdDqtWjCpTmcssVc+Tb5Vcss7PNwMFK
4o5EHXslaL/RVCUeQbSzNIiG2ULyG81Buk4TZmAIlBkg2ib9bxpB/xkqPOux+YuYK7APto0c8a6/
+Dgu5xw6TYwmFFyx8lAHXsUbHOR3EXLKJ8K2V/2Dsxz5+N0QA1UxyAUcdM/QQnIw1vnNeA6h3U4u
+Cx6Wo6AYYtVyQE6WKfwGGbhMz+aZFL0nneDh/HXe3rIuO3Ivsb62lp5LxIFHqbv/a3pWSyAsujo
O8qjWA6wdmhDj51PWc8iSIW5bsR8H9zGH62556SmPcUKNG0svAkzI5c8bnHsgSRreOXqQLWcRLzE
bYcJlyEki8phvJGqhTA5fD2J7DP8ARlcT2IsSym8/xwoip8oPFZcT94pz4eQJw+mdcy0Gn+rck6U
6cF6+gkFOdrtDXWVOJtRdZNxrXsbMCU9fynL8H1uOrlJ9+HoFs5p+OHzGRFDByRytJnYifGM8bWY
sU7XY1kF4Rf/XZGypsVAE5S4rqfPkZaZ/OkcWDPQEz/7AIYWKyoktOd4klmL+SsmPbzJypBCAwVh
cXhffCOOxhMtkucfFCoBYn234M+r5wWWX3Ceoo/+NAPfc/zXmdinSeuLMs6zlKnhNY3Tb4ABdpbD
UL2A6k0S7Agaa3ubg8KCeKsiLWl7dMxDmCJc2ZLkCspd2TMo7IxnIY9VFtw6WgYys2m1CJONibxd
6pX3N3y2yq5dP5KkTt9xZgpsdA8XjLkcF7rgmdoxt4V28h/dCUtvsmxNYVqFvpTzlAp7+/g3GQd9
TcVjg4bWrWSLEzLrVAhPoQatBAE0pHw89VLzogwjEw06H6mDgekKT4sxidaMyf7JR5idHmVBaBnM
r2vUkEo/WzY/ZL9DYQzoPh26yei47KUQHz0NQt7F2haHaQ4WxRdxk6QMU96Wns1ItMfqunAmrg+K
CER2OsmGM/Jn2kuZKePOBWmp25vYnGOb4DA3fC8f90xHTsuckPjGsyHiSunF/mr/EVKqt1JBa72n
ueSycgfEZF1ihfv5nlJJaMNgp5dBYxSXqn/tcEngRbq9uOuEQxzzx+bDyK8p83rzUDWgWiru7umc
Qgr09BJdyg7I1cC22pmf2E54Kiqr6kuPsWFG1XVsOAHcOuVy9ylg9eySu6J3L7NujmGqojT4+lom
rBvYR22MPRqmcg+CuSbfHiEUUHW2Y9/zX9/J94sOxI3OmxzER3BXmzxuwhTeFBgB5msz21L0wUCA
SfLcCcwF2RTp0T8FyxkR9Ei+3Qz5NdxSv97XvVnLa4t5sHqZHffZfUqYYHks0t6aUu4SPQhxJ36j
ciXt2EStFWMLPiAi4q46jj57afXYS1do6pVWu52qKVdofOhpambYsylNGPnX6cYdqZrXVsLW6oWC
wWOn1upu7E9oHWm84wsvVFm2r65Ra2+ps3kk8FbJx3si4otinM2epIGZFMc2h70io8GAm3a7VCdA
gB+jwimgFaOMIdlOfaU3y+Qg6mvD4rBFRUnaCgrjryY809ror6IcjIK+bYmDqvSyrpH4o1PwqXWz
0Eo0OYPiGmb+r3GqDVJBn4XR9ePjHJdzrZirK0jtG6pTfLtV+oR2aHMTThw49Ix5U3IFKf8YbGtr
phWYqDjRFVufg8dLq/aA9VCS0yFF3XSXrNTkUSuge8u4eFE3HKNTKedSzT0XakrFeNbgC9O2tFh7
51sQaw4jwGwOBD76ExlRLRUalgq606bmGJ3EAw1UiO+vGlOhO5Fi7xG0WVgohj85R3X49Eo+5DY4
NOU6fc+uLTFxwTDww1GvckenFWtQI8CCzHPTITokFHEUR84s/twdHeFinxxo95s4+3jcVtNs3P66
orivxsm5YP0lp8SLZaBxeyBfB2W7A7me9+pxAfH92orpbCuR5K0ZRB8hGqIgqTIDFO320ydI+4rg
vDBbXfOW1CesVgjNOGhWLuWZD2BrVU/FGHxTiOTnibjfFt/YpKskEV6HTrWAyGZ/W3xa3oE2XKSm
IWqYjMXgwB+UkL0CqtNRLXtatG89MnuPB3HtJXyluZCdO2OaZBL7yhjuL7dhCag9qRItJoG1rl0D
8gHoFIjH0XL0lZBS2x9PsiJIhEECr/DivsYm/6yl4P29zhMBx1eWTjoFJ/jfLQgSDbCLPb431Or0
r8kAiEOOfn6FWLfMBe1HL1we5PagJl9WObMyRD4oHYSNX9edBaAIFaBUjdbZDQd5Q6RdBodgcZBw
V20oR3gyx/468CED5AKFhaMxNk06yqW99vN4PLUPhhiAfdJ1h7TwT8+EGKaAnfy6P6mIu4e0LuHz
sPbW6JtyNH7agXiHVh+S2tjfEH0eF6To1WO4Sxj9SxME7rsMEJO/KZBwBp0L9hKrdwkoTaEUDb0U
dN0m31HNf3ytHG8fRsfcliJJZ3ZNVxNUWBWndwyYmfgukWkZuicxzjY3IRgAzm0CriXGq13qRrwI
g8ZAYSnrtW+/W3NCXNs0JY9oT3p7sDwhllxP1XOjcPNQAtXJlUo1xhHOvYQZs4Pow3CJG3bqHEKX
lTHGtZW2DalHjHGS2BqYI090wK1NsGX5YyMfQFjDl9+YHspM0nWSoN93DJRhaC/TIA2Z16JT+gED
3p9jGAk7XOdD+9RxqLzY94UssmqB7oNZVTNfazSwHWXb8UhaC1XDS+L54h1XavztSrgj0LHHoaax
QdI5im+FeNhl+bWxbYxso5gTePq9eaABmROCLTbwG1nTnBs61sJPLi3K5KIQFgzgrUo3mJ6nm7V4
YXUl1PJRiUCbvSREK2Tbna9/rVo3AL5e+W30grrSF33W0rXeB41c2R+Pa01k8hkFhrBMd7iJzICv
mieuQBTeQ9Nc3oZDhLwB/08XxaVaivydl2OZJ3AeGkUk3tL+mtJLMC0J6s3Xh7LGxfrCIO1Gj8C5
bFBUjo2x+GfuJ4t0nCzJlxgHQxuFj/wOJIbRP51LoHgi+3WryVjPtbW9GABpDZLtWUo5kLAfElAt
r+fdEQtDtkfBIx9M0euMEjw5d/ImelHv1auC6X4cL7kbGn/PsNfrLJ/xzlPAj5W0JeUlh6MnOR0L
DifC5K8tWOfCewCZTFj9QJV8Y4G+ajjA6DWLUWwVqNtiXes5TInsh/nVYM9zxSeznq7etxHufWEi
o1f60wA7jk45sgHqIiZ2HNZ3GcquJgYhVCxw+RTCvw0hAr2jvPl7+jlqRpxtZ1Ag+CyboncFckU6
oAwzUALDwQO6QpjfB3bbx5Gvx0fVRXxxH906bciSb4kuADT1oE9oM6PzUINf/TsT/BYWdfXW3Yqu
M/03egbNwetl+WhgM7XFo9CgAVDoJWpJ9qtUw+3lfQ8mFMZ3fkNN3gMKzZPe2R6CLR98YMRAaF52
Wk45gW16czdEHMwc/CmaamYzWMD4Mh0ENdQ3IMr64PHWZD0JysbX5uqb/aADiX9eNg53BWFpcfik
Q9zU07hAa84NBhpIbvP5df6n//CzOHDvpjX6l13dkizHKglzUVDfpH9or4c2JclAXacf4s/6yi5f
+OoexKI3j7HyAabVzisSKrnvscgvuieyqyYKQDSnaL6pcwquD3/M+sDVDf0RN6SOj1RCniXFem4B
jLdt/7a1YjqNzrrz8SDQzI94WNRe+vUYDm42Epy1fszLGX7tq6MZhxDSmonItlNAX9/t0oG/PB5R
qN544i/ckUDPHpSyOCHHLjSXCcuYELyYmuHC+q8m64dPLRa1t/2Ic67f3iAcUXuUfHqQ6JOd56G6
hOd6XcMouCtgs0ysq0dnMsEQgXlJMcqlsegXf3DDDFBn96nWKhvaCyAB6ibcLIc7vD+jr+CCGILf
KHsCdJt482+NhURht3icSod9AZBN2FmqVTKR5PLmf3UX8SCtYkbZjSY22VMp9cweqvrbYq4aTh8Z
Jt5t86uYq8acNWzSd4tylIAoNEafJ6YfGlhm++0+5lBj9SCbUJ1n6gtgAdQFJo/rhHHQw01+r8TP
2GTKcVnaZCnrSeEf0mI5+kX9NZsEo88lhtDHpAjpeosDM/iXbCzKQSGf5nUk/e4ymbpRJdTuKgb4
cTYTCn+jfpbFESlRYO7p5uo5fb2n5eNo6osTr4xM9kJ+YjKI8eLK8mKENcG4ta3LV0o1tQ3SDhKK
YOcW2ENVNTxr47cRg7aCeYbN+Wp+Vm/E7MXWYRnj1GMtbZh6mfDNiMJOf3JiasTRZ8FSW3rTRqkJ
1nKI6YtWUMQSP0VUSHfVpqJ/VaJ5J7cyCKQOM6kuNx9YKMsOySfHYWAoM1A9RlqNLx9dVpIEQ3uI
78XrNbnNVnhFu3IEIuJjTaVweO1dLmCnJY4aGv7EBGztUE+lLjJLrbDNfJNRfieiwHsGGDRno4JA
DTnLVAfs1EPBIVG1AZAwuGSS2ww9dKMeow7gKHKoEXBEf2GJiSUXgEDlIDyFh64Y8059ph/lfZwK
4o4gEkvEAMJDhCzwbA5/vbWimreWjFMFkORuNVaqJydGP8zEKq+pDAEkKGVNSTvFBBhVrP5sY2xs
8IWVJB0zY+1/itn/gczIIWDaeoF9hkCdT/Q98RUWQTg3iH+IPbyimiTW9bKgabu722HdNh4HWqKf
TqUd60P119JHpE+ScFhmdd6X4dmpBZa6KPtm5OsQRYnfc6PFr7DD/vlE0S7gsxAV7UVe8l2s1jYA
Awi6j+C2MRR5lFq/Tk9YOjfK1rfM06EX7MgobtZYuveKZo7yfDZo6xxPpDTDwPTPo/NVddbwDSVC
xBgCbczjSKVaIu/A0FgWYCkRyTUosnvpa0vZf0t7Vmk+NAzlqlPoL4km0MZv4sfkNjuM5n88rtKL
vZH54pq8FUqyVZmk6NrKId/2kZOElR2Csl0Tmbu2tktPo16ZfZljWB71y1rLXL3TrK5j9AlZMALl
NvnTU2DKjSBqcIAZiLrZypH613OIXk21WWg2x8BwSDJaIiD0huO4okLJE9zeWd9jBUIBbE0PdVW9
vR4DGBFZfDQqTH6w1OdQaxH0G9PXLT3f+/ek5nT1oDJaNNkdHJ638mzd4NJCfRB7mG8z3URr3KEb
+eYlVyt02QvsAvGNHp+U+aMyfnnyGLpiNunRFqf26Ex60M8hacHFUmbonFwFFmOpzufo1dZykJWZ
+ln/nZiQy46p7XRQ1IborXZtbBH9gWRg4WDiuBpayj3y9IuqnBbmtazaWfuzviO+ABQVCKMlcSIO
O3Fth+SOKc58Dkvn2dZP30ruaP93VLrRSieoSMIZqQZVzTNMfhUPIG1swVyvyDfnDf2fWmiaaXU7
uV6GMV5ljt+yIFAokJyLDD5nHAeud1NB11GNcV+gjQplz/6hw2Cxfm6NFaXpKS0q4+fqc2t6Q45C
qvFOeBQhgMPpseyOUV9DjYB5n+DfkGp4QzGNTKSdRTaA1/gqCMJ3OnDy9PmFi1GyaHA3e6oa+QmL
xKCkKhDSX4hj+dvHjMwla2YVsyk3h1q3ZHSZZa7NTYMy3Sho2ZDb/K/pJHtd561cazE+DNl6RMnu
xZQelTvOQPJw45CqX1Hon9Zt6+ubAIoKsaFCuvfCe/BBmduuFLzkfpYlYxuwyrZCG+Bno4RJncvb
d1WKe3ZsJccVbJg+8i4+2VPpe/B0DrOoC1q1M45NRoPdQESkqQEi0A+NQ/7AnVUnoBXYYmgFbvno
dALV82two85brEGp+7YA/Fhsv63fQexL8S68SnK4QCs+RIWqJ1Ye7dVeXImd0nYrEygbaT/PDxZT
zxvuPGVOoaCQLU1BztJklOw7rg+KNnoKZB46uIQtjNWpx66uUsTlckJXKYkmpMfNMtjOiS0A3Rl5
oPtxTHBqmAR3bwlblE5C/HfgSUHhSNfPnXa1S6UDdtA3wWe8AEKRC281KuClJ6vh4hQ/0fMvMGvu
okWwgkUMc/9bP591rNACe4hoPDBnWYbItIilA3BhqIcY2G8eYa6V7tcjtP1xaWCWtH38AQ8trOjZ
NSJqw5/dp6pNyb4wLQFA2ZV371a0AvNFnESqJNcpvh80fSETiwTQx5/E/MrGvZ1XnqIvwAksRHQk
Le8Ks+PlOitY3DPDkMyMHNkuFjfaJvmrAeGIOqfdaWPfREA8sB1aD3M0byuurgTwGySjUHBvUaRm
XzhMFCze2vrjzDuer+CRGS2b5AjPma6XHwXktSmRoOHns/MSzOI/eKWIhqrnmEb2GSCBuhqTfA7s
tgwK04WhhpwoRNL7jTd0OPEbwLMPF3yHqjSYCAtgoV6yj6TtdbhiR0N+YBMhYZ7IdIU3JyDYEsp9
L9dP4D383T7/wxTBYHMk7n5ir3+nDZwlBPASlABA3MTnegml3gVlaRtBuKUj56Y8QzgapHNMh9Gf
ZKDdTlDDirA44kn40kwjYXrg7kUEn5tY1q1g0pqs6B7J5xCk19HW5XJYvuaGrmDnq8OPm583a6Xo
BTWZNlPP7ly9jCUrxpTLMHltExEpKcFgWlzgnqKm8pcdJwp61XuY0CN0JVh8TaGDF/NvgluJpLoy
a09u1ycu+/8f08XYJRWwx8sGrtPRo61gqhctJdFHsa+gU96msyLSqUe+3eiN1FymFDl5U28Il7F3
amPKEKbDh+3nMdc5j34njuY1DbxPDlWWcskAW78A/tos8leKv2Yk0H0G/cVbKg/VErPSJ/GYjlaY
0XdiDurZnJwatr0ODnVMBC5FynhzQloaIC9iWfygj7E2l5RYjdh/DlfLWUHJwDMa6OK2e5gol9Y3
Z+esAq2fryxoda8IqI4koPIomLtQga9aBbPhPb50CaABHgIVm5ZKLVq870OzZT0O5ysyfYWlICQJ
pxlqijeUL3kVhckK19lB7fRS2Cx1ByO2AhqnP0T/NFjEmRkmp6N6C4G36ndqlhwjCY2Wtuea3pmp
NgdEU/PHIWJeQBnbqVMb862nViUjURDptOSy5jJ6ds7j1zxawmjSP0afqjnnYm0Xq6gEM39Z8aA1
RfcqVI3edGdseVCaoyEnAXnstvowsT0FT3eUMw8CEczNqqp7fFR8zC1eDueY66GzfUw167+wfVX/
05S1akVjTSJgNGTQe88Fi9nzKKTLveBbBuO+VsVWApw/RL7h5NjHeKTObhzemKi28rThZ1DaGJ+Y
vJ2ujQiaSLxsKmpQb5IwC+qW9NwSMtDtudC4OqTkFMtSFoYe/vlAZqFGBUjCgRODKS8JVCs/VyXV
YUh61eAlLLrEP/arbWd2kQ5hJRJhAxeo1t6zuUWu1wwKUF6VpHFYUJr2uU8feLX5kBUWvKTOh8B4
mv4QsVTaJw92cHM0A/zhCvO6+nReiIXMTnblx5UQWd+JfIk1h3yt+Md2X0BlHWHvxHPRLaL/DLki
KVeBsUZye8b9qeYdGfQ5iyRKLsq0O2IhyytTjVKo8oq08rz+8eCQHegmVvSQisifwpbni81FT7AS
7k90oDUPWe2uXgdBCp2tP/BR6EuR9agx/aNJf72+SIr28hv13x2ImBoqY1NgkuHvO1+6zLS8x6YY
t4U3c91cQWGmBd51Dela+UR2LQGeWIN2Aekdz7O69rslHRPNCv4OszBwC3gylAqDqOHvanXMX1f5
eR1GP9iCnjJ4CCMnR1UB07hXCEchDPhpOzygnoTnQGy+sOX0N9BL6ZjYE8LDPcniLQsXAf4bb51E
9YsGLjv1pDFx5tZIEmOu5j3Yrv3LrJZKrc4ko50Nv7j27Hx3Qqeca4hhuLiLWoxmofT/X152Plwy
pcg18ByiRvFxPvqP+ZpaVtnz9fdj1LeA6AASixLtOYTYWQKblQZpl9UU2umfKXTNeV/ewvVBVoNp
HprrkA0M9VgBaG2P1nU0iNzoohxzav+z/apxmBTRjWQZgT3Z+6ffljLF1+ATOKycMHg9c+bikPVe
j/IOWclLHYqLwWXSJxUej0rwC2+mPZgJ/IEcmS/hr+ON7bauUJC4pnrZ5YY7w120ND3RPTMQjk32
ZEKFV8GOw0V2FZ+cbOn43c+tFhVkKmHQK8dUP+vZtTmqGOWdbNi2VTYID7IKaty2Y39LPGlOzArj
Y768FOXWv7n7fyfLs6H013BKPfBiVU0bSMOTu9JpmaupeGSFSKMDbGwJoIrEL/6VZqamtinZhxCI
RF0Yw20ALZO4aNDkhU5rGYoaCDBcNa5QPhpn+ZQhqdgzobQ0AaGTTympb6TF7OVITJ3ldO5J276f
VkiUNKbM7Ew2S0gJzwIDEGQw+yWplXZ/uiCgzB03B9zganzn3rzZhIS7any/dqvYN7Zl8yHa0hTi
F+F2l0LWdJGj2umguA0DanN9IELgjw/wd/G9ChfJ7c/Xy7vdYO3oPdeAKQ06oQRQm+zsNoHtVG/O
x5USksdvgx3wlRZlXtB1mAtjV5DjX2Fju1cpWhUlddssKJIL3oYc9mpyqrJryWX/h6hACI10tFeu
jWbCl3gqm+l/LQNvq6ATLMjr8VmTBsSYEJcIzNcS3IbCRHTzbDPa+mEsdX6EIEVNt1T7ycMXbrln
M976ISN7EPGiyWerwmqLfEdwzwRgPV84HDU0TUyxkadqxi76JCwu/GMJRpLeRtGD5z/HciSGowh8
gnDtoYerPmIlegyMHnvVuRtT2MmO0NjBuGbK5OiptuWw3FGspiMrdB3B6x+dR9ANIx4NQRLAkXln
O2BNWeVn+wvye3fwzy2uaqre4rxVlLku8awVWhzgaoRgAZiOkjEiHOyYtNAlHb66pwegxxGcfc8X
z+vKStrujYtL11+3Ne6WohHdAoeLlU7inmC5IAfpf8npAbSeXxkvyDJu/asKEUXDgsw3Df5KSS9z
rsVFHG11LGjrBAx9i6htGjCoFAKoWROyQ4FA1yEGz2wSVIdaMD7dLjtUsHqjFK9/25nDiY0/1+Fh
LpCeO38yGnBRpxdPI7uTozRpelfJ7SCl1pTBjtClm+wwFNESLNukN+32/zSe8fnsGz+KAb5R7bK7
DUYfUdYbAF/uwma9TLJpfzMQX7/BkIy/085KhWYygrtHJ4IjtxC/nFp7IO+aEDnavbJasI0HOeMo
DWDsSy9g0we2Eyfn/u1npRvp1Y0g8Vc3x/W6YafEHcYvpmYHaEM8ZXlTuSo4Thep92ep+SuIBEus
9I12f+Wu4RyY9GhznL7bapHSJhKgZOE3q2AX20ncstS5hT8I4h/LSj6Y2+fBZD+FWaGQrS0JXS7D
P5SMx5yyHggitnSqyvJ52Qz51D+GAwrdCLh6e/047xWT8JHMY0l8D6G53FRm8oVAMaNBDQru4Wu1
+zMdPwXcytI3lfr36bgfTuV/Fem/RIhbT8f8li3/rJVBm9+no44G8dBKH9uSvukuZz442m51ieCR
ZCA4GrrdnqVQSvmiZg0PBtyFClaPUvqzstbfPhXwXuLITqqjn1giQ/Vrhs9mdn/4ip/N3dCsB+k7
DCogSkS9C4dysRcsp9J6d51FQBaP02Mjfh73xaJ0lwSdXQ50tW1UkoM+EvxdzMrTXuhisjYbJ0/2
DaO2d4fL0c05AzFzYP68gfHi66Rhhk2jSUOnTFxR12gLJB3upIXYqGjnk2VlVvdjnLqJ9OSC/AKU
KKJ8mhwk94LfxcauyA6dJMe2N4yJKxdvdPrqJlL8C/P+QlXYO3I/rAhSK7FtwazgdVcXF62ZOt18
3tzcuAdv9FqZLPVNR0EvUXNJQodcCWcm3Cm8Pl/OMneVeRZ1hcy4G3Fl16h4Tx6zam+GFfkU8UpD
4Q8QVC16xQHkVSeDaLGoIelju8S8cYqmcTFltcM7eaJbdgBZxsHunfdx1wTaDC1g1AHM5DNIUUii
KjQuyBa+LBb2lh4d1aVYw3Hm1r/fgWxNiBZs3C0x27UMbPHk4K6h8cIOkPd1yQ0GMJFuLSu7hENX
TXxI0fb34E5q3B6knYsTe8fUUiVHbZSpcOATnIbDE46McMncY6vJm1QMSeyIGhAIMkENdTVKkIk/
JWvq1E0IgwhB+fQV3f6JGAQ584ucccw8eBHvfbLo2J82V37IQqf2HOgJUnlUZrcpzIrDInchFBIH
9m/ygo7TK1lxCpDkGJkYL0WtL5kX7QywothYgLHqoDG9IFBXEhxehDxsAccr8HDvQJox5LMID1L5
o/IwysBpwC253IRMFr3TzvHG6JPNqrFJvA6ojtvIkVNTVd87s+gErwTGclCkOfCeIdfcbVLJtpxY
11FrzbK+1uqhUAlyQgZVQAV4civn60smknWEpp2qGEQ87bjchI0Y1rGmxbrlT7RismeW2PFzd2jq
v9XknJ3kgkkjtew0IyhiXG4q2Qpcald/uhKFH6doOgWLCSu34LvGf34VvzsYYUWRMm2tvZZewafw
t05yGE6ZCbqVsFyBZz+aNmLoxufuKLvguA15BfTgxdVGCQNukVSE4jCPOkpwVq9Me7ABLLfKaOX9
DhpeL0ZTWcbpq/fXhwNkqJEK4bJeLiyF/S+kcqPiEqxWKLcjXX38+cTF4cXjAFdJwKBFzXL2On6y
jHb4j/7HZ2CnhOvXwTYiPNtJxyHHKCaZt78y/9gtN4RLUBxNg/sq1U9krv6rrb5NNM0VYnaYGVlT
NgJGIZ/k+HVxD7MO3YlQUg8QNSWdGkgyzpV4oOO8iBDeBfryi/duTHp5i7ZTYAn+snhdVLZkKTeN
/ramv4XeOZrNOTE0xMoO9PH0hNkzXyyWfibdgkIJgV0BxjrOElO+yiOaLo6cjh+7V6HU19hbRnd5
TmWNW/4a56w6B9haP3pcbyzW+rX1w9cVd65ZpaQXqFS5rfPWhEJEY8f1+H6ZHVzeNlNtr09plu8P
LfFxHroRUaKImjHA4Q0i/ru0WnbmlQv4HajhbhGkfqltuzeIGyzHZp8gFy591pwHwdW2cGTVW+TO
L08zj6hcMrEpmMUBCgKB2zw4IxxOAXl4cZbXzvaeQA+AQ2aUpp4/IS1Zu6P1nGxovgYtG+L2bhQ2
dfLL7wPoxbLq3DxmUdVZZaFDsTBL7gE4JpqnJMUrCTO1EzIoUEwACVJkvvk5d3xq45IeivewsGJW
yFMXIVfbisCAmWbnzm0JA/Cs1fDAmEo045JYOjj9FEvzhIFGnQMuqrjmvRDn1V/Qoc4YqZFgYDbd
zF4N/95e2x0xBjnGYYrud/Hk6ch+A8Zhp9015AL7L0jNYMZFHPt9dcch6Zu1B3ny1l+h0cR1dHgR
wLgojIgrzFLaJvEIdhh/OJrqEPDGk/4CWOiyCaV4t6ef0dzVqDpviaUiqJq4TVoDiRPDUItkHrmX
50Oe9Pn2YuRqXV5VeT/G5iSAw6rcBSB7Xi5ITnI5cLC4fleOBdxhsiY1YG4gwF2zwinB2La09nOY
I1S2EkhWC7+i0kn3I/G86Umk1TnXra/hDyQ78qVyxjBJ/JzyHFvvHY3S1HdJao9vsGf68e7Xad5B
W+C91ze/h0nyKHOLzZpKSJjk2O4Xf0LS1wH8Q5sA6wyIY35R92MLTLdScdzj09WaNUogoJgnTpcG
4vhgkMOSMpMv7aZJOBVeaOHMl0NXwpptIL5Za7SAUZtQup2Vm3D+EBbUfTVn8ZPPzWNqanJATv88
a1T1C6aHrp93TlEx6J04XrpP22fXa1KSxnfv+Yu+sfsK66sbKb16NT7g43F8trlvkrJFE/c7Rh4Z
+nPjj767Ab5AsovINF88q58S8fWidcuxiF5ilhMtrWuAP108wI9s9zgRusRoxSxgaaspp+Zzqz6S
zKRY27W/7ZoBYy7t33nvfy1VnAQHv+Ixvw9evabb1U5f1u1m1BUmAWNGHeT+xlsPgOOS026lhzib
xmJu8AkzDc0mgqLMkXlqF73GQBh8rAo/aJcJOZDjXMjXO4mmj5ODotEzLT8D5d8U3mOEm79cUxJA
Im61GXt+LXuxHa2E2IzHCMkRd4m+l5gFVeOy1tn4BW09ytPHDR+YmPL4AtfFtjcn64SDRtDjW0Mb
UWdjK9d6P2dj3ZtjlY8ytyXAneCCq6vl3xivLYL5ri0Sz54zyl9SqeR0TSLGenPrB0hkfdNfrLXa
RcoitfAz6cRf5avEfYmF+mtZMKod0E1HhQMUXOsfK/4iPwYHH797kLW68Qz63bS5ApK5oidfjTH3
ZLfhtRFWhF62sDLKb0lVPgM+yXK5QLD+EHKZvIPAQXwsgdodxWbfGJLzZf39ou9fZ4aMLKwfbXg1
wpTegRrOSvJb4GclAJb2z2Zm8nRei1imdKYOKd7YKX675U7eXLW0OetimZhspSLpELetgfgJj9zz
6C1ftkTnFEvYWV6EmYmGC9uqt8TV8MJy5Gf9j6K9P483QEtmGgKJ2MwAdsocZo57UsgYh52ElgDO
LSInBdSDXyC4uRf/AEBiPkHV5dcTOWfnWzKjiFHKxgnxISDaYhHq1F/1/LFLDyagqfcHTcf+1aC8
KlnYRBMElCRJLmYz1N6HEJarVDvVnzhTXFg/DaMui4tDQUQbmi6gv97wdETfyhH9JliEMWlMkjI1
W+p/MwdFAcXfeh85MJ8rtMsK60fOQyqIW2yT1cQZpF1O1Hqo3KM1QjCthu6/weMMSG5VgSyiOkbu
JoQZNRiwEgAnRZTKyKgiam5mvRzZK8osuFT9rjgZ5K8iOlzfwt/EOkKWoGSIHqdH+uS5CqZ9rW7T
WS1Pw64FH5XHJGo+dY4VgIIOjIwosFNxNx44V1XK1+nfIkLTHROa/pWKaummePoBXgH3UWhvZkpJ
nze+lpNho42BGmPdJbaBWxFxRPaTPzHjtTED+BOm1rz0h/HIAS8I1Unh4Z8Ap4wnAQDXhP7G8r6H
jUfWr3+HAxTibALRTXpEmK8Gm9B1DFCttqXg8MVyMt3TNHALRuemW2so3wDTRHJcxacSpgI8N+Un
Uq7FdQdFonGhL8I8AEu779AhV/t0ITnfB6Y6DxP1xPAGsQqPFaCeK0tuybI2bZhbVS/pLprTdYa5
XiUDxgA4wO6bqXAsD8qB+ikQ9dxLsR2yOHBxnB3XHUWkBlh8r5a++MZrk8dYRz45EXjTEUl+SW/g
CceY1mAgzHdAQgOWLEQrwzR7NUCSjRV2gWPOdOCYTIomJc0SM1700sRZsH1DCfjz0oi6MbNJQVde
l0xb90WTRYj9yg9OVUgMLWEVyltL8VEb4dfEiRedKwjMScAJgvBJZN2fst4JPiXtn5KFL5IjWGxU
iEREpo9k9wEVZ8hdNEiFw8cbF3SNO/yfPxRATsgGX03IFXZgm4kDIoSgcyDWxUmU06PhSGdDY0mv
wHheyBj+yhLb8ws/tb6ime27ht4cVXfGBxrxUogtxv8/lKP8db/RpZt80B6B/vIL6ZtdUAJUcc/R
fRXYh45hSxHXYi919uDlUVTyTD2Bodxek5GNgU/2C9dzYTGL4W2WLSYV7vR9pJaZLkbCzu5Aex9p
ycwT4/s4V7n0otUCfGO/0/2RYt8QdbWbZ3LRDvNpUMzpxqSZEQrUR6fNeMHXmxBJN00pDyF7YMGs
2Sc73ul93yY9CmPkViy40EvDu6ZsvRBpONRB9bjLKBx4/Vz6uwN2LzuSoiDv1BL+yhErNB7RYO1e
ifn5NvULxNN9mnAU3FSkcNyNB37O3oWZ+b7nGQgzAflxoS7RY+cKMVNv31Qh3bLoXsrGfhmWDHrl
lZeVIVXMFka6qkYTa4HSwRQazh4UFrkoFUtFrzc/wUE91ABsH8YwvHkimiTKqAbQFjF4pvkskrQX
2hVE1FDrCNfy83uT9PrSLv7lVm7Y47j2A8DVej3ClX9y8ejc3wV/aeqv1m1ZbgRcqaaiJ86C0Z1U
PlQ+2cAzBmUwYPbQb4Hh8fwfAe+KCR6sjANa6D5Mbz0JJuVZWJ4IwXBBKZNJ4yuuYXv4bHpiY+S/
SesBsKedYPs2eRB4KJ7jlioDx7Gdw+01rzOJ7TvqUDF5h1C1DPRKAwt6hLXvG4tTSX5XCfglT7XZ
LLCcD55310OCmx2PeVDJ1M9eurTNwy9BZDdmdEZ01kO4U+TsA3ZtjlyBDHf7bIAmLPVPyDSE/Ih1
VPv8KX7Sbz5PLycQULV8YzqgFjHlDiT084+jE5sOia+z2YExSX1GC0YuKjNwtnQ708vkMdPThUte
k98Pv1fj9dVOedm9NetJ+usAUaa4g+dwAwj/JZPgO6TKJARhH0X+TAecaPKr6dM6RT9AOMFPAaMZ
OgfuJSRe6lF7UHL+HV3ZJwP3sMhsp4O+M/zET9v4+EOC5w3dHK8MQNmSkI7HVAZhkVe7WCAIy7+D
pq7rHxX+3i+OaaWwc0mxHgt4JeIPfGlLDBAsdnPZY1RmOsC9EMX2ScR51cMWNrTuVKuQ6y8Kk5En
dcig8HFH7wr75SZt55ElEVN9/cZC/Z6BbarzLCHFif5jlinJZNEWSTEodhCuG1eYfUHDxUbCHfbE
TVtY0c5QDDXsupujznOt6rvRYGlnv7AA7DYt2gsD5ECYVEYJ65zcbms6K8ND/kDRJo3LFwOS0OUY
ka539UhoruZBn9pBaWuCS/UBfti+x3XIK25wPz1WXaEzz5PzpfxFE2WhciFDV1R7lJh75esxlhNW
WdcPxJ4XLcL3Pj1qUT3W9c3v9HrU4UVkc147DnTVj+yWUJ3OZIS9jqlvdCoy9KzhRj6JYxwAhHVt
vXLmChN5DzYS2NdOhZbzoMt9ZwhCmyWJihAG8PSlB5I9IBR7TYpsPUZF9PE+AkpD9Cld5RklkbLn
3u0gZJrpvpTsaFIUbHKf3ZwC+Q9ULrWoNGItZMi6bS6cTuV7AUKvl1OGhoSGHNxlhojiqN0XG4A4
K2KL/MyJzRPXt1lpkRj1LVVOymH6jGrLVAWTH77u1N42q8gx5lucygbyMmVL3Gvz/6V74Q8gOAn5
Sdsdmuq0NcBFBV/jkN0+nsE/L63LIKON7IuLBmO5EYi63JUIP1UAS4EUVYx4yQVhnW5i9+UTTJ48
7zv893Wx7ryCv/DSapqg4t09sk0LMWTgcsKgDlXmFeLOofWlHnQ3QBffBmhYgH4uIBR5+G/AOfUi
WvjUy4vDc6qD+lKEuuyJHIxEJ+sHHXTrxM3DD1CjgQAzKRGAjBwHBkNydJrj92a28+cPuDx/BX+f
mxiIKOgWKk3uXs63h4TkRFKgrDGQg+7htFHYXjnJMlO1xtuDumgRJ3QUu+s8oBOQCFI/pi5eXLdK
jVZOBbJ32ItKSgWgRYwBAwwXd2BJ5uWy0i58xXwifSvLt3CTBXuo1i/vGLCfcEZ7TxmAYxmD1e5q
rePc7ZMZwDHp0fv/DlrDnDJ3cyw22ycmzZLQjOgaUKwHM9Y289MAQP6Sc0UiOLZ1Gw4WnWp2mSmr
KNt6uOgzgDylbk+hFyVVbBJIr1vl98/lJ2cOryfjj7HVYL67tNgUGm/XG3CeuuSt/KcHMCYue+sp
eUSev0yXljTnZJZ/mJtTBq84zrGMquB83GI4YCJqGeE/QyCf4yAwMPUFoK4/vcuCZBvVtbNVmExo
zdVGqP6A4KQoA5jLzwbW8jkq1eqthtL37ZKRhenKlKmVOZpbBV/k+IoVqU7P7qBxkTH1Hc9aRDCQ
t+nGvNJSIomogKbhcDrQwudGTHXaUgQNQq7m8GxO093d2A2DZy1Fff9AT0F/8D2ys/BEQrK7Bqs9
1PvCUZk4gFaZvwJ3+qzn4sFLPnynaEebZ+LU1YTBwho+q+xmbMmzh+4vQKWZkbV/TnImC2fFSfN0
ItO3Wzsbqldwe4Nxs9qkL2Vr1XiPPkY9NDVeySa2Yq2ycyNiROiX/XFjD57/wUk754qrJ7WHQnNh
Y4t1GeXlpweXKeS/vAf3H03Um+HyyVwsmMFlw3t2CSprAOtxMFS18X87g+RRD9bRwAtG6/xFkPJk
KDYy29QMJtovY9vLpuuK/QIruZFZQpDM3laJZIMmnSnkgcvXfW4pPgcBzyDgHzTrBW+suYGDN7CG
UGu/gGPxZEIWFpwHavEAt56CfKidQK4zhGyyNsowBr3kX/KLV1IiNk4J6ASTrapRtI75d8J74NEC
C+k+EF86vbQTMDZgfpY2wFSq2kYOrCh4gaiFH+vHvNv5FPCijZsEWN8B66AsGuCAZDvZwWd/r/4h
vG+FZc7aD01Ee/4wT/SHTzLaqqAH3XQhs2l6uS8a/IMGenmd+C33CBcrrPeqPcVVkL0Koaeq8TjA
wuekK7zDgqWNUvrZ9zKsgIfRTWQa8ao7l4VS7Bs/mOMaUbdZFKZoDHS917+p5sF4Su3paODV4SFG
XGjXZ5/7Y/0etGCZoDbYIR18KiuYNXR9lFrZ4A9V21DrUpaA/dP4JhJ32j5vYpBCT5J5gxnuwP+0
h66+8rn3vYYPk6/+u9b1sd9kXd4zTa51tXK1xXbukk8GkLxYfgxnfiAXSBzsb6VlwNr2sBSEry00
laY0bDQjXVm1TZsHnLxNMfec15SCvJm7mvxzL8qpr6d3MCdod1IDYs1jZ6lZLOKw65C2D6v4oAwI
IkRbBjEb/UosfuMCQs7h17NmjAfundJ3Jx6UGB4gAcxDIwbc/aEFh5B+yUJmIBEOaVA7MJ7lBwCl
gJ3RSRGx8h9eHE8iumRFiLGFSTmps+yieiHb3PDf85RYIYk0me0EnRmfrvxG01JaT2BDuGnrB/dZ
Y7hie3jjpS99tGMzXkHTQ2rsueNOko0yZh2pI90puLt2RhMC3AofNR0os06Yw9laIZStCxZb38ub
pmvp5m6DLpcS8GWA3t8yihzsXPr/lowlg05xFctPqUxl07gXHEfrreY4HDEfBtNvkjQ8vPTQUfiZ
gDATwoVMwAof0Pt90nr7s6x+7Rof8dsDZG9IfVted+nM+8587X7AWNRDnaS59bpuPRcUhIKsIDF9
t91HdY75zal8v3VYUwglcwnBB4byK+0px7YC/4P7057c/yuNLmgcqgjOE2FUUWIGrai8h9qPWyB8
NWNAA3f3yK0Co+VRw+TEP1LKu2q80mKRnVgJS9g8YFzkRpvw5fhcWqkhqJ4pvL/2w5YM5Ajx6Gdu
2o0FoSfUSt7vwKkwefNOwBE7uQk7Rdwgx9gawK8dFXSV4rl3O2DfUHlTbdP9RVmRaf+EabdYnawS
4F1EaQvToBQFhLjpTSDNPniC7J2p/4B6x/WfqIrPgeYpR/jMr9QHM5O+wLxVD9Y74KNHPKeaEdwy
Ve+Ci2WfxZApfDUHsJXTUuIgJIHzNIgaH+kKHWr3wIPx20wG1maDuTwZ3jynsIJOSrk+RmWhQmo4
niOS8QIvrD7jo2qxktKBv+xHc5d63owdLGFl1WVzPivHXpC5ngCR7RwI69Buglnn7Q9x3uv+dDK5
1atae7ppLg1Q4myF9YDQfzW7OzxfSHiIYfQ1By72Be2q/cN/ST7spk/yIp9eE1Dl1ZZWeq47EV+l
Exmp7uQxhoCfSQDUg8oo2c1L0wSZCnhFx3XHIOqKkQUhFFYByW2T5T/bEMJ9NJyLO5awGoaPvAOW
S3o1Hz7VK1cD/qkKEF51vm4vUsKeMWXP9eITOPz32H7d1oNE/4hpQgdILR7P2xmuUTA+Qv+Qm2Yv
1lktLPD5ATIpbLJr5rK9+Y9uLWKnd63gBEK8Lh+N0E/L98LTGeF9d16wpCVDHuB1l1fYMg86LXI8
VpJzw35N7KYnK/4fRjt4Xycfy9+45EY/NMFoGZ3GBhAaIkYc+Zea0IsesBJVaXbVoydkyBlyP8ed
+W0rQtyFSXQlM3WFkrBZUOg7gomdfs5eXeccFVWhZludSknEXntdNUGJQFjtwwdaClXXeGO5yfGo
NfOXud9BSdYV+RKXjEQ2EsrddD43P+xo55jHnirsy02MPfhu6n+kSGfA7NGWguqfhEgLdBFOUREL
LpSNJzcnswTHOdRLpXsL9/uFQRcA/H3AcXTqunA9bl5Hb8fymIr87qbzXrxehF5UE5zKyzC2jMfI
+9dTIH1ajYRim1U/oiN5w/KXR2FHMGMwlv/pRgMllh9+TVc8hMk/qU4wH9/U5CFWSECCRaJEpstc
SqNE3K3jGLeELgzmqX5iW2BSSCObYCXHGeTmSZrtGoL9uBaKy2XhRRHFMoXcpjWblWY+JigjwhkG
ziztFT7yArBTz3RZXun84ZUd3GSX4mzBQsrjh8tUaHpgR4L/DjRHAnxjkLZ3Fvf/acI7SJuYQCdp
oEGhuEl+IV8jKMzHtAXfJvu0EsZ5GuFkYUYMrumSuVhbEhJk/JXmElEQgC1gmN1FAk0l4yAHRdv0
SEtu9nKopzsT1lhHvYVCWVsWFOUHfcpwkS1pWYsFE68hbFJM6A7mMTKYAtQiVDp/nzFi/7bC3KvT
H9dE05Y3bzHJPykR75TBU2zvZ6JeF3C/KWqka69vtIk4sEjeCN9ULIg0ARToofDLWA0gnnZ7VO1m
fs2FvwqANBlT4V1uJnO9eqf3S9lMxsCrIP42J33BrpITRMnvYpmVYD3Pu5xxs6zbo8AAAj5G80vo
Qr89ITvicJi3JkdQPK4IwaQyOXPyQTTlnffNK0vKQexrI3/LmlOH5ccb7FDkaRSDXHhe7gVtEkkK
NCAYfd/zMix90/yuAPideXWOz8a0+j6627OccRe+vOdRc3JGPdq7tGzDzgpspu8StreCeyPYgnGm
uTmMaw0ZBlzvrGRgFj53QdxgyL5/p50PiYv/tRIkFeuXu5cVb98onA9KcqrptaC1A3ypi7pjJGU+
yJ1EwFXyrkNWECPt5vQOJw9R3+fLkiBcv2ksUXPkVYtVimwgaKDaeNilA4t+q3ag7qMzAXgeC9fe
9/dcP2CUOMErUEbtc7lRkJU+jiJ/6EajygTGUZVDWEBsyN5tTvh4Ny7VmJs5XfYR9TkM+IBN9OxQ
ZKf9//ft/9GSIsuHWfjSjq6ZeqbLRuQk7dmcE6hEnqi5tec4Mpz8vL6wnTFGcs3SzwTL/mcRDJLK
bM8SqK5nI5SZHUlc+HKt01C/uFcLnpUuiHcthsl9GqQ+e9ZoddASSFBOZFsLupUGf8mWzzr4UZ72
Zf0GnpnV1SZgdP/ZUGrapNzGlzTIB4OI5eStMkZY+X4DvA7BWC96tTK2l6zGOi38IcdfuvJwVJ5r
X8S+aXpRKeQD69zdGvZR21G7Bo5VUIPQhymtnrP3qciABzOoCEdhgGk2AKY08K8nexGOAOyqSPgy
fYXi9HdDfN4ZGZ8jkwNvMWEpPNz6O4a48OvCsCWh4JdLVksBWFA42X2+rC0lhTFrHrBpNnnmZw9Y
cDi6+ZR1+Ja6vRRfGBz64xmgVndVZem9TNUdTtAPitn3W+SVF8YzLvPMRUoqCVvRoB8FYaRwPT5Z
CcAkYC+BoLBbJRVxmAGHzA/1YURuIq5JGODV2MRjk/eEhXcNtO+lQtmOx2Uuh0z7aWQ9VK+zSv+Q
hK2WCi5JANpBGy24rzAzqWo8UE7da02zcJiRnjE5xs1w5z4G552Liuw5FkkwkBmwXIIwGa5K5J19
/rIbrFE6RNmEAEY1/NZc7uvtT19kO3moVJMSLodPVjcOsawHI3O6MKAHY+BJoYScyh7MQmdmW9Z/
oNi32BFGvkrKCEm2rd4m+2I4nEpIcZbmU7Qst0XDuty4oIJWqqdaZ18PYJ7+Zox8j1T0rlcfd10C
t7tUDQ6AbstP4UYgHUrbEEyCRvcSQS/fn4dbKDUyEpTY1zYhUif71hs5wQ/aKaf3obusBzNavuMe
/LBJ7Ao5S+3g/I80FU5SgDMxJFQ1cuoeJa+5CRhFTQ8ust0CdrKVXYDM32MDVjzQOLdtRguTyYe4
yhjmDyamw7s38LAjPZ+6TB0QWpxD6VaIp7XpQlGaafQMdjljOGHukYckR10+gkhsaeTJgrD55Yz8
CmwWgu7gYzYzci1WarWO08+vn3IkkSN6oDwc8ipapZOnm450PLIFlVU3slrHaDJKwC+jI+QfI66l
YVPVvnLATYwQ6vldkodvd2kbB0tJs73spbZUww+/wVX3TnqUY3zgBylD40sbDiJSJyD7L3qi4O+q
53TWiZ/dJY6VZxqiNk9zCRrgGmgrB1+LYM8cSgP3b1VFQ70pAStnvYClJ842I67N+6I+dggRRzWr
7wi4vSHFI2zBIr6QxiKW3klc/C8QXmj0kaomdQxLWq2JnlZlvdj6ka4KtGjmbu8BXEkJ/e0ZB1ne
kx+LS1cyzwYsU+swtvixy5BSVTIz5DRa+uEWDh3ftQTfR6NjLLU9tLNyGJUPh8PdFMqy6mDUPWSp
axZLao9FHxflCuaAjtO93JLF+LMKfEEIiWKyE6aJhZ6MVWSUKcZe4ilpkZLA8i86heobR81LZ55k
0/TBzF+cg9jsDP3TOBhhkEmObgMUWYboPieZzXfw8ZoCdIczfMOBSm6yT9s/bAF3H2RbsiBOgTMP
Og+RuT7KHAUFTRqDzrMGW3ITPb7vps28/rwOurbBUmzDKce4L8wjza+Udx+wOuyGi0L/W5EwPLgz
E+8fJ+y4QzBb49Z4oJxJbK4RTakWv/EyLrrx32VnB6jfpnrEpaN7KYqr4YsE94aPPWir3YTTpgPi
q4spLq6gO7/XyU84k5BtyBjBdGsi9lkAxkUEoz/gpGDKbuU4gylycDregAG/Ac5du1KYC8YkjOIr
uO7P8G/+5+lmzYSxroAV5x/BM1wwDuSH/jIpvs6G6KCjVkMWyrLRmpNjS/WhhvPGMNzkI6j4Bjy/
/X6cx9Asz6oF7V95/8QeA5x8l7pBytX0ildUQgNGqSK6R+78PdcfQqtKcFKCd6DMlVeZHyVjux1O
POX5KqhlM1Yz7mq3hvI3MtYzd4FqzM7oEzN503MYMck1osPNbgueisbbDQjwZE8RWz6bQFntk/+Y
jJia8i63tl1dbpTOB+JQwgJLdm4DzhcsQAljVM7wieMhMO1fBsRZS9yJcLOqkbbdQ4qSDXoXDhfS
pDvfjpHFukXFkMOclBEiu7ycpB3CYGjAPP3XrpZ6vzs3Ni3t4WoBmEp3D0VzARvzaksdJwHsJPhh
xOIU/b8WLgyuhhRx/RH/WT6tBbIutjksnb99ge8Q32eAApg7na1ytBqjd9Es/xrf/rswvT9VwOeX
Ign5z/6LtJrnW9dFsFRraHHHNwh7vXq8tQQ8AhPk57i+9OPI+nLnvlwCqcBXbnUKmZXH0wg8RPdR
9oo6Q0fWb0Dt38mQuQxBYARFFhRmw49lFFLdGFAfJDJjuaRz6aZSqv5eFfS1F2Ue7ulTj3QKFKoJ
3JYRCwndplJr6B44MH24kNyhATJ3iKzqlXmwpPTxW8ZBqAANfmlJq1cpEMlmJhwkP0oQdzQtAN38
MgPBjkeTYvgj5pAcX+InPPnFmHiIf+o8HFRBNdE5wuElOtMr8OXgFQ7/uncl/YgIjQdO8cbYeCyu
Fv8hGPZTCaghklnTj6VYc4siEXcKJejRrj4KZItm+K00StI4JP7Ni9vFAh2PhtkPTWcnx8d2THpX
641j1TXiIs3jSr41h7phIBHDmvhQxwGAG3GFVtLfGaoOCWjwBYN6vwUT4SKZugeJlmhqvwEaIdGm
tvqUkaQaJx3Z5tqVK7tCKHsTNvq7UNDqtayvqbdE87SXWAqBC88AnIs1HvoMMlwjDJ/xkPcBEYlq
sxxfdF+8Edk3KZWM0HCkeNfpUlGVoUryovT+eqTmg9U3bM9hVTSM6y/EF8h8VmRg65w+DWtSZnFo
QfuKzPgE7mfKv+cEx1b5rf0Esm+4sQHb3vxDNqOoxxJv6q8Egdr+g8J6bvvDEvATE4O7kfolP8S6
FmAzWG6H9JZuSyXXXHT6WEkIu9/8+d57Wz6NBrfZW4tWPLebL5PTifZnh3rbErAeu/pM0+uphi2X
7IYtynFA2PdgE0FToM1Jj/v2oRmnv6aDYkPvQIQDXb0wOtFMF8CRO4hyyx1G8XFBB6tOY7Hounl+
jw64pjJ8sN1WWnx2iHsLW9NiJipzeZkTjA0jnIyNnUan0xM3+FAZ1vJ2mcjcs9rQ/PQygnvx/Y+d
0W571i68InV7Isrvj1c9NeK4nQIVN1y4p23ZQXFMjMH+S0tr/ExUAQ2sWQ2Qk03Nk8rXoRCheSxI
k5WiqxMtnrLTvNiAKbWkyKm9N40GJGqJG0q900HpDQIJPiifLr0cC5iyzDn3YNZgcWme+28ZiiP0
5KVAaD9GJYQoiNlwbocNYOhpdeccz3izqAQ2oJM89NtPncd/SBq7wHkkiDwrbx0/D82JlR+JNRto
9YD1H8aKD8NNY7C8Bq+nIPKd9SXATYDGwATl7MB+pyZk3Cf4EmpaoYxWCXxgaE0DrN3Z/k9+zpnG
lVIYZWPbFxGUlX20XRdd4tpn5xnvjHFJqF75cpjEZ1EEognwWGn372O/14lEvSzPvLCnJ7YdtB+p
bDtroVNN1fGBYwvyXxABV7Rt92ywC+i4q2rNC+DQNxdXRd8q4szp7oxrJjaDgpT+XjDw1SaCufi5
F/kawNE3ARoXxenW08vq/8BiiTib3PuKsFGCxWcjtAMBwPKU3Ckn5xYB0EQlJSnf5IQw2fmOEwCn
PUaJpXkvMBS+RfnOoJfj7nTq3NmQkkbu5Ua9/fTz92nfPRmHcgJoR4Sml/ecs0WT35bnlYdHbYse
zFgn6qkRhfMY+0qHKEvIQtOhavJLNYubR6rOl6ROkIaQBQnxHUr3XoCOYlp9wyugH2ubCwrPhj0y
bReeOOFb9z4iYT9wkxivwyeRCqRerxID0MyjbqEf9JOUcqMVarT/Vk6bL+lUfqhemvbgd2w5R8E9
/gp5epOQ1bpzrfSvu+7nXrZdE287RkZrLqwSt5bY2o+E84I5coGIQ8DHpBV6T7AVEtMufqLeJv4o
kwtwnpIdF//065LCYojgbW1bKdCyry1Kj1deOu3phH7LaJg7szymuB7HlhEcl/dF/jbrX1KJ5ZWl
kbGFkQ+9wHttKoAvsjoLYKkFlEXEQZMgA+an8APwKWgnhxSrBVpSrWmIM0WsBOnrqULK4V1ma+8e
7paK4Z3O6BwvyVngClv3WqA9U+op1dTUZzMdRpfSTdFnOnRRXXGoS6DmqeuL1CQNPVJ0mmQD09/D
VVB5WFVi34zeAR5c/xBr7hULpYpCUG4XFyZLbJVFuXhfWODC3/ukq3xMnZnkVuigjwDbPIhVgXTp
TQQ6j8LU3XJ7ZX4x9HD+yf6BocBjbFfBRh33xDx5B1vd7kmN5MgT+XSkG8L8vvAZ92aHiXd9nFpi
2myf54bU/GcsH9Pknhm219Le8OsAqyfFNRjZ+3H9E3mmyXurNcE2cw0YPM1KD5UM6AcVWuK+ffRv
92BMDor4h4TD576RVNYBNp0QOqSZ9Z83Nv1P5Zn8Ueb7eeruRtwe+bcJltduP1wGHs72PnrkERNw
P11sRQG0QNzespapXFjNixLslvAiZN1K+2k4ZfQ+B564iLMi0s7Q4onVfRVfPcUDUlSJ80XrAnp8
Cvo0Xg6y71JzWmSbWMziaYEW24NZDM9+U0fH4X9k40BScu6pPzdTxS8EIYZZ5h8O+JD77t6YqF20
6S9wDgGavPE6B8h+tqMDXyeiZ2+f86EFAlCoHfKdRy3ZWR8Sur34vnv6kw3k3kq+CGSjWPsGWt0o
s9cS3++CXceRR3HbNuqLDjmwu35z457sqH1M2skIDUWrjWWOES7X9GmpEyDb2z7+F6RFyFQFSsKF
Ze0MxRNUjhnaf/g/X8jFzg0TVR3ZeIvgcDnGJFNhJYL8fs4Iw/5q2oDZHEl8DtzbycQ+f1nxw8sA
kO3yhAm/UWGSh7sRZcq0amZH5eqOquYRZDDLQylVwqdbRqS3++DAbl9w0F5+PUm/8mR0wTI3mQZ3
YZ6xImxysj6IGmE+GkOSSeWkDA0VhWylbaQG0JozUdbDtn8xaUmg+mddPsclqbJVjEyY60YbkMZ6
nT8XFIn18XudiEW2Ilt+lYFE21GIbJ4k7b0heAv7P6fyQyVOw94EPdyJlooj7azD7T+wZx89X5So
WTcAK7cihyAVp/V2UEEken82QqLRglo+imJ+Vz+a7AoN8EhOZMUuAFViLxvL2BwRsbTw4FhanSwp
RYURY9JHAs+7lb/O5M0XXtXBBK/dBWxnVfqw86VoDoV/F8F+CBWvDgcxe3Th9v4g+ukTxNVDmPeP
zOEst5cugPhu1pT/snGdZzhwukqKG3VPZnyOAutREjhP3z/VtJoLOQBdQI8WVi27O06jQ+/4EjKN
kkatqVJbMFEItOC3kLtgXjzij6uPkH6mQ9UyM1MYIZF+BlI3sloem960yCBUgW4NQeQVa6oWQbMn
/AeIAPIqQuqbgAZPVi8c66ArDce2ieIweRKyD3E2pxDZSouakWIFlewILHu0ewVbHiHiOwQnRu2N
vrGCmDmk4m2FY/fd9RKUMTCtz52OpOtJuZXSi3pyqgQA3u6jk1g4TB4InrOT+7gEutppptixjYvL
ghluSP4J/lC5N1Nlk3ZeOUz8QcYxWgFNP6fMybWOY8eZhg5YfPgHh+xKY1/PIkecdDZxWl9Vl5kK
CVpAG3gq4EUky8zZPn7+cWkR3eXDCOAn0I/rhpgly7izswYdsiZ0btxyy1YTYG1811bZrqjnUiyt
R53rYTfzfzzMMcC0TbN/4OLgA/6DQ8hrndLrpzg5PwVqG/sGO9/6/Dt9q3t1nMyh5JLbFWjc0FcX
zVRyf5llagsljyTdKBZ0JA1rJIR/DCqSf+RscETGb+wknF/UQUsrO+vomFT6lNPXjIIt6H5xjkNy
tmQdChtGt1e3RhPi78avowQhluUsUsxVcEoVKkr0c2mH3ntXdXbvP3fkahNCxej6j4VQRNSfYj/G
ONeIycQBt1vGJ3HIO7FOGorwqLkiB4vVxESjOT0HfVuA6b8QprhICRSK5ySGR2xBvdu4n2YkT81X
s6efujSLKEm+2kGjNJydRss7h+r7UVlzsVXsppWfmYK6ZfDw5O8xoDLz16hvB4dL4/nfcJaG5kMu
c4ET42P6M9lfAdMAjPm1Gqn3++zXQH9oUveIYAuIqwviWi7gDwc1XJNo5MhsPYIW8m6zSVEFiZYf
LuCwogdOYkO0l4KkydjEq0bVL3HGxmUWSxQNRrAWg4+wEuRLWZjxukSTuP37fKwvN1/UIC8OLiDt
zy8WGpIqBAUX/7BMevXdMKHSNfGs9HEPDNziXm3YGlnHEyYsjnAbCf+p2m9Xp235OweEGl/hhQ==
`pragma protect end_protected
`ifndef GLBL
`define GLBL
`timescale  1 ps / 1 ps

module glbl ();

    parameter ROC_WIDTH = 100000;
    parameter TOC_WIDTH = 0;
    parameter GRES_WIDTH = 10000;
    parameter GRES_START = 10000;

//--------   STARTUP Globals --------------
    wire GSR;
    wire GTS;
    wire GWE;
    wire PRLD;
    wire GRESTORE;
    tri1 p_up_tmp;
    tri (weak1, strong0) PLL_LOCKG = p_up_tmp;

    wire PROGB_GLBL;
    wire CCLKO_GLBL;
    wire FCSBO_GLBL;
    wire [3:0] DO_GLBL;
    wire [3:0] DI_GLBL;
   
    reg GSR_int;
    reg GTS_int;
    reg PRLD_int;
    reg GRESTORE_int;

//--------   JTAG Globals --------------
    wire JTAG_TDO_GLBL;
    wire JTAG_TCK_GLBL;
    wire JTAG_TDI_GLBL;
    wire JTAG_TMS_GLBL;
    wire JTAG_TRST_GLBL;

    reg JTAG_CAPTURE_GLBL;
    reg JTAG_RESET_GLBL;
    reg JTAG_SHIFT_GLBL;
    reg JTAG_UPDATE_GLBL;
    reg JTAG_RUNTEST_GLBL;

    reg JTAG_SEL1_GLBL = 0;
    reg JTAG_SEL2_GLBL = 0 ;
    reg JTAG_SEL3_GLBL = 0;
    reg JTAG_SEL4_GLBL = 0;

    reg JTAG_USER_TDO1_GLBL = 1'bz;
    reg JTAG_USER_TDO2_GLBL = 1'bz;
    reg JTAG_USER_TDO3_GLBL = 1'bz;
    reg JTAG_USER_TDO4_GLBL = 1'bz;

    assign (strong1, weak0) GSR = GSR_int;
    assign (strong1, weak0) GTS = GTS_int;
    assign (weak1, weak0) PRLD = PRLD_int;
    assign (strong1, weak0) GRESTORE = GRESTORE_int;

    initial begin
	GSR_int = 1'b1;
	PRLD_int = 1'b1;
	#(ROC_WIDTH)
	GSR_int = 1'b0;
	PRLD_int = 1'b0;
    end

    initial begin
	GTS_int = 1'b1;
	#(TOC_WIDTH)
	GTS_int = 1'b0;
    end

    initial begin 
	GRESTORE_int = 1'b0;
	#(GRES_START);
	GRESTORE_int = 1'b1;
	#(GRES_WIDTH);
	GRESTORE_int = 1'b0;
    end

endmodule
`endif
