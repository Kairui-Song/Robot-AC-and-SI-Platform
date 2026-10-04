#include "fake_left_arm_bus.hpp"
int main()
{
  ArmBusConfig config; config.watchdog_intervals=1000;
  {
    LeftArmBus bus; bus.open(config);
    check(requested==std::vector<unsigned>({1,2,3,5}));
    for(unsigned i=0;i<4;++i) {
      check(EC_READ_U16(image.data()+i*24+4)==0);
      check(EC_READ_S8(image.data()+i*24+19)==8);
      EC_WRITE_S32(image.data()+i*24+8, 1000+i);
      EC_WRITE_U16(image.data()+i*24+16, 0x27);
      EC_WRITE_S8(image.data()+i*24+18, 8);
    }
    ArmFrame frame{}; check(bus.receive(frame));
    for(unsigned i=0;i<4;++i) {check(frame[i].position==static_cast<int>(1000+i) && frame[i].mode==8);}
    const auto before=sends;
    check(bus.send({{{101,15},{202,15},{303,15},{505,15}}}));
    check(sends==before+1);  // One send for the complete four-joint process image.
    check(EC_READ_S32(image.data())==101 && EC_READ_S32(image.data()+72)==505);
    incomplete=true; check(!bus.receive(frame)); incomplete=false;
    send_error=true; check(!bus.send({})); send_error=false;
  }
  check(releases==1);
  for(int scenario=0;scenario<3;++scenario) {
    bad_width=scenario==0; missing_mode=scenario==1; bad_vendor=scenario==2;
    const auto before=sends; bool rejected=false;
    try {LeftArmBus bus; bus.open(config);} catch(const std::runtime_error &) {rejected=true;}
    check(rejected && sends==before); // Rejected before master activation/first send.
  }
  check(releases==4);
  std::cout<<"Left-arm PDO adapter: group mapping, image IO, WKC, send errors, schema rejection passed\n";
}
