#include "../bridge.hpp"
#include <iostream>
int main(int argc,char** argv) {
 if(argc!=2)return 2;
 mednafen_mcp::Backend backend;
 backend.read=[](uint32_t a){return uint8_t(a);};
 backend.registers=[](){return std::string("{\"AX\":123}");};
 backend.disassemble=[](uint32_t&,unsigned){return std::string("[]");};
 mednafen_mcp::Bridge bridge;bridge.init(argv[1],backend);
 uint32_t pc=0;
 while(true){bridge.access("write",0x8620,42);bridge.instruction(pc++&0xfffff);usleep(50);}
}
