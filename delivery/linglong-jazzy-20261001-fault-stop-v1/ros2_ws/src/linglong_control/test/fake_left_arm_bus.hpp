#pragma once
// Fake transport linked against the actual IgH 1.6 public header. No master,
// NIC, ioctl or physical drive is used. This checks the adapter, not ROS runtime.
#include "linglong_control/left_arm_bus.hpp"
#include <algorithm>
#include <iostream>
#include <vector>
#include <functional>

using namespace linglong_control;
namespace
{
std::array<std::uint8_t, 96> image{};
std::vector<unsigned> requested;
bool bad_width=false, missing_mode=false, bad_vendor=false, incomplete=false, send_error=false;
unsigned sends=0, releases=0;
bool emulate_drives=false, stuck_enabled=false;
std::function<void()> receive_hook;
void check(bool v) {if (!v) {throw std::runtime_error("left-arm bus test failed");}}
const std::array<ec_pdo_entry_info_t, 3> rx{{{0x607a,0,32},{0x6040,0,16},{0x6060,0,8}}};
const std::array<ec_pdo_entry_info_t, 4> tx{{{0x6064,0,32},{0x606c,0,32},{0x6041,0,16},{0x6061,0,8}}};
}
extern "C" {
ec_master_t *ecrt_request_master(unsigned index) {check(index==0); return reinterpret_cast<ec_master_t *>(1);}
void ecrt_release_master(ec_master_t *) {++releases;}
ec_domain_t *ecrt_master_create_domain(ec_master_t *) {return reinterpret_cast<ec_domain_t *>(1);}
ec_slave_config_t *ecrt_master_slave_config(ec_master_t *, uint16_t alias, uint16_t pos, uint32_t vendor, uint32_t product)
{
  check(alias==0 && vendor==0x1097 && product==0x2406);
  const auto it=std::find(left_arm_slaves.begin(),left_arm_slaves.end(),pos);
  check(it!=left_arm_slaves.end()); requested.push_back(pos);
  return reinterpret_cast<ec_slave_config_t *>(1+std::distance(left_arm_slaves.begin(),it));
}
int ecrt_master_get_slave(ec_master_t *, uint16_t, ec_slave_info_t *s)
{s->vendor_id=bad_vendor?0:0x1097; s->product_code=0x2406; s->sync_count=4; return 0;}
int ecrt_master_get_sync_manager(ec_master_t *, uint16_t, uint8_t sm, ec_sync_info_t *s)
{s->dir=sm==2?EC_DIR_OUTPUT:EC_DIR_INPUT; s->n_pdos=1; return 0;}
int ecrt_master_get_pdo(ec_master_t *, uint16_t, uint8_t sm, uint16_t, ec_pdo_info_t *p)
{p->n_entries=sm==2?3:(missing_mode?3:4); return 0;}
int ecrt_master_get_pdo_entry(ec_master_t *, uint16_t, uint8_t sm, uint16_t, uint16_t e, ec_pdo_entry_info_t *p)
{*p=sm==2?rx[e]:tx[e]; if(bad_width && p->index==0x607a) {p->bit_length=16;} return 0;}
int ecrt_slave_config_reg_pdo_entry(ec_slave_config_t *s,uint16_t index,uint8_t,ec_domain_t *,unsigned *bit)
{
  *bit=0; const auto base=(reinterpret_cast<uintptr_t>(s)-1)*24;
  switch(index) {
    case 0x607a:return base; case 0x6040:return base+4; case 0x6064:return base+8;
    case 0x606c:return base+12; case 0x6041:return base+16; case 0x6061:return base+18;
    case 0x6060:return base+19; default:return -1;
  }
}
int ecrt_slave_config_sdo8(ec_slave_config_t *,uint16_t index,uint8_t,uint8_t value)
{check(index==0x6060 && value==8); return 0;}
int ecrt_slave_config_sync_manager(ec_slave_config_t *,uint8_t sm,ec_direction_t dir,ec_watchdog_mode_t wd)
{check(sm==2 && dir==EC_DIR_OUTPUT && wd==EC_WD_ENABLE); return 0;}
int ecrt_slave_config_watchdog(ec_slave_config_t *,uint16_t,uint16_t intervals)
{check(intervals>0); return 0;}
int ecrt_slave_config_dc(ec_slave_config_t *,uint16_t,uint32_t,int32_t,uint32_t,int32_t) {return 0;}
int ecrt_master_activate(ec_master_t *) {return 0;}
uint8_t *ecrt_domain_data(const ec_domain_t *) {return image.data();}
size_t ecrt_domain_size(const ec_domain_t *) {return image.size();}
int ecrt_master_receive(ec_master_t *)
{
  if (receive_hook) {receive_hook();}
  if (emulate_drives) {
    for (unsigned i=0; i<4; ++i) {
      const auto control = EC_READ_U16(image.data()+i*24+4);
      const uint16_t status = stuck_enabled ? 0x27 : control==6 ? 0x21 : control==7 ? 0x23 : control==15 ? 0x27 : 0x40;
      EC_WRITE_U16(image.data()+i*24+16, status);
      EC_WRITE_S32(image.data()+i*24+8, 11000);
      EC_WRITE_S32(image.data()+i*24+12, 0);
      EC_WRITE_S8(image.data()+i*24+18, 8);
    }
  }
  return 0;
}
int ecrt_domain_process(ec_domain_t *) {return 0;}
int ecrt_domain_state(const ec_domain_t *,ec_domain_state_t *s)
{s->wc_state=incomplete?EC_WC_INCOMPLETE:EC_WC_COMPLETE; return 0;}
int ecrt_master_state(const ec_master_t *,ec_master_state_t *s) {s->link_up=1; return 0;}
int ecrt_slave_config_state(const ec_slave_config_t *,ec_slave_config_state_t *s)
{s->online=1; s->operational=1; return 0;}
int ecrt_master_application_time(ec_master_t *,uint64_t) {return 0;}
int ecrt_master_sync_reference_clock(ec_master_t *) {return 0;}
int ecrt_master_sync_slave_clocks(ec_master_t *) {return 0;}
int ecrt_domain_queue(ec_domain_t *) {return 0;}
int ecrt_master_send(ec_master_t *) {++sends; return send_error?-1:0;}
}
