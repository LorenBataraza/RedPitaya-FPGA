// Copyright 1986-2021 Xilinx, Inc. All Rights Reserved.
// --------------------------------------------------------------------------------
// Tool Version: Vivado v.2021.2 (lin64) Build 3367213 Tue Oct 19 02:47:39 MDT 2021
// Date        : Tue May 12 12:18:36 2026
// Host        : LoloVictus running 64-bit Ubuntu 20.04.3 LTS
// Command     : write_verilog -force -mode funcsim -rename_top decalper_eb_ot_sdeen_pot_pi_dehcac_xnilix -prefix
//               decalper_eb_ot_sdeen_pot_pi_dehcac_xnilix_ asg_dat_fifo_sim_netlist.v
// Design      : asg_dat_fifo
// Purpose     : This verilog netlist is a functional simulation representation of the design and should not be modified
//               or synthesized. This netlist cannot be used for SDF annotated simulation.
// Device      : xc7z020clg400-1
// --------------------------------------------------------------------------------
`timescale 1 ps / 1 ps

(* CHECK_LICENSE_TYPE = "asg_dat_fifo,fifo_generator_v13_2_6,{}" *) (* downgradeipidentifiedwarnings = "yes" *) (* x_core_info = "fifo_generator_v13_2_6,Vivado 2021.2" *) 
(* NotValidForBitStream *)
module decalper_eb_ot_sdeen_pot_pi_dehcac_xnilix
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
  decalper_eb_ot_sdeen_pot_pi_dehcac_xnilix_fifo_generator_v13_2_6 U0
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
module decalper_eb_ot_sdeen_pot_pi_dehcac_xnilix_xpm_cdc_gray
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
module decalper_eb_ot_sdeen_pot_pi_dehcac_xnilix_xpm_cdc_gray__2
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
module decalper_eb_ot_sdeen_pot_pi_dehcac_xnilix_xpm_cdc_single
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
module decalper_eb_ot_sdeen_pot_pi_dehcac_xnilix_xpm_cdc_single__2
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
module decalper_eb_ot_sdeen_pot_pi_dehcac_xnilix_xpm_cdc_sync_rst
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
module decalper_eb_ot_sdeen_pot_pi_dehcac_xnilix_xpm_cdc_sync_rst__2
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
`pragma protect encoding = (enctype = "BASE64", line_length = 76, bytes = 95264)
`pragma protect data_block
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
9/YDWu+OHhBzWGMtmPfBd2E=
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
`pragma protect encoding = (enctype = "BASE64", line_length = 76, bytes = 50704)
`pragma protect data_block
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
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
