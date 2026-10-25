// SPDX-License-Identifier: GPL-2.0-or-later
// Local file transport. Called exclusively from the emulation thread.
#ifndef MEDNAFEN_MCP_BRIDGE_HPP
#define MEDNAFEN_MCP_BRIDGE_HPP
#include <algorithm>
#include <chrono>
#include <cstdint>
#include <cstdlib>
#include <cerrno>
#include <stdexcept>
#include <fstream>
#include <functional>
#include <iomanip>
#include <sstream>
#include <string>
#include <vector>
#if defined(__unix__) || defined(__APPLE__)
#include <dirent.h>
#include <fcntl.h>
#include <sys/file.h>
#include <sys/stat.h>
#include <unistd.h>
#define MEDNAFEN_MCP_POSIX 1
#endif
namespace mednafen_mcp {
inline std::string quote(const std::string& s) {
 std::ostringstream o; o << '"';
 for(unsigned char c:s) { if(c=='"'||c=='\\') o << '\\' << c; else if(c<32) o << "\\u00" << std::hex << std::setw(2) << std::setfill('0') << unsigned(c); else o << c; }
 o << '"'; return o.str();
}
struct Backend {
 std::function<std::string()> registers;
 std::function<uint8_t(uint32_t)> read;
 std::function<std::string(uint32_t&, unsigned)> disassemble;
};
#ifdef MEDNAFEN_MCP_POSIX
class Bridge {
 using Clock=std::chrono::steady_clock;
 struct Breakpoint { std::string kind; uint32_t first,last; };
 std::string dir_, reason_="startup", hit_="null";
 std::vector<Breakpoint> breakpoints_;
 Backend backend_;
 bool enabled_=false, paused_=true;
 int lock_=-1;
 uint32_t pc_=0;
 uint64_t ticks_=0, remaining_=0;
 uint16_t input_mask_=0;
 unsigned input_frames_=0;
 bool capture_=false;
 bool auto_capture_=false;
 bool save_state_=false;
 Clock::time_point contact_=Clock::now(), poll_=Clock::now();
 std::string status() const {
  return std::string("{\"paused\":")+(paused_?"true":"false")+",\"pc\":"+std::to_string(pc_)+",\"ticks\":"+std::to_string(ticks_)+",\"reason\":"+quote(reason_)+",\"hit\":"+hit_+"}";
 }
 static uint64_t number(std::istringstream& in, uint64_t maximum) {
  std::string s; if(!(in>>s)||s.empty()||s.find_first_not_of("0123456789")!=std::string::npos) throw std::runtime_error("Expected unsigned decimal integer");
  size_t used=0; auto n=std::stoull(s,&used); if(used!=s.size()||n>maximum) throw std::runtime_error("Integer outside allowed range"); return n;
 }
 std::string command(const std::string& line) {
  std::istringstream in(line); std::string op; in>>op; contact_=Clock::now();
  if(op=="status") return status();
  if(op=="input") { input_mask_=number(in,2047); input_frames_=number(in,600); return "{}"; }
  if(op=="auto_capture") { auto_capture_=number(in,1); return "{}"; }
  if(op=="save_state") { save_state_=true; return "{}"; }
  if(op=="capture") { capture_=true; return "{\"queued\":true}"; }
  if(op=="pause") { paused_=true; reason_="pause"; return status(); }
  if(op=="resume"||op=="step") {
   auto count=number(in,100000000); if(!count) throw std::runtime_error("Instruction budget must be positive");
   remaining_=count; paused_=false; reason_="running"; hit_="null"; return status();
  }
  if(op=="clear_breakpoints") { breakpoints_.clear(); return "{}"; }
  if(op=="breakpoint") {
   std::string kind;in>>kind; if(kind!="pc"&&kind!="read"&&kind!="write") throw std::runtime_error("Unsupported breakpoint kind");
   uint32_t a=number(in,0xfffff),z=number(in,0xfffff); if(z<a||breakpoints_.size()>=64) throw std::runtime_error("Invalid range or breakpoint limit");
   breakpoints_.push_back({kind,a,z}); return "{\"count\":"+std::to_string(breakpoints_.size())+"}";
  }
  if(!paused_) throw std::runtime_error("Pause emulation before inspecting it");
  if(op=="registers") return backend_.registers();
  if(op=="read_memory") {
   uint32_t a=number(in,0xfffff),n=number(in,65536); if(n>0x100000-a) throw std::runtime_error("Read crosses physical address-space boundary");
   std::ostringstream hex;hex<<std::hex<<std::setfill('0');for(uint32_t i=0;i<n;i++)hex<<std::setw(2)<<unsigned(backend_.read(a+i));
   return "{\"address\":"+std::to_string(a)+",\"hex\":"+quote(hex.str())+"}";
  }
  if(op=="disassemble") { uint32_t ip=number(in,65535); unsigned count=number(in,64);return backend_.disassemble(ip,count); }
  throw std::runtime_error("Unknown command");
 }
 void poll() {
  DIR* d=opendir(dir_.c_str());if(!d)return;std::vector<std::string> files;dirent* e;
  while((e=readdir(d))) { std::string n=e->d_name; if(n.size()==36&&n.substr(32)==".req"&&n.substr(0,32).find_first_not_of("0123456789abcdef")==std::string::npos)files.push_back(n); }
  closedir(d);std::sort(files.begin(),files.end());
  for(const auto& n:files) {
   const auto path=dir_+"/"+n;int fd=open(path.c_str(),O_RDONLY|O_NOFOLLOW|O_NONBLOCK);if(fd<0)continue;
   struct stat st;if(fstat(fd,&st)||!S_ISREG(st.st_mode)||st.st_uid!=getuid()||st.st_size>256){close(fd);unlink(path.c_str());continue;}
   char buf[257]={0};ssize_t size=read(fd,buf,256);close(fd);unlink(path.c_str());if(size<0)continue;
   std::string reply;
   try { reply="{\"result\":"+command(std::string(buf,size))+"}"; }
   catch(const std::exception& ex){reply="{\"error\":"+quote(ex.what())+"}";}
   std::string dest=dir_+"/"+n.substr(0,32)+".res",tmp=dest+".tmp";
   int out=open(tmp.c_str(),O_WRONLY|O_CREAT|O_EXCL|O_NOFOLLOW,0600);
   if(out>=0){size_t done=0;while(done<reply.size()){ssize_t written=write(out,reply.data()+done,reply.size()-done);if(written<=0)break;done+=written;}close(out);if(done==reply.size())rename(tmp.c_str(),dest.c_str());else unlink(tmp.c_str());}
  }
 }
public:
 ~Bridge(){if(lock_>=0)close(lock_);}
 bool enabled() const{return enabled_;}
 uint16_t buttons(uint16_t raw) { if(!input_frames_) return raw; --input_frames_; return input_mask_; }
 bool capture_requested() const { return capture_; }
 std::string capture_path() const { return dir_+"/snapshot.ppm"; }
 void captured() { capture_=false; }
 bool auto_capture() const { return auto_capture_; }
 bool save_requested() const { return save_state_; }
 void saved() { save_state_=false; }
 std::string directory() const { return dir_; }
 void init(const char* path, Backend backend) {
  if(!path||!*path||enabled_)return;
  dir_=path;if(dir_[0]!='/')throw std::runtime_error("MEDNAFEN_MCP_DIR must be absolute");
  if(mkdir(dir_.c_str(),0700)&&errno!=EEXIST)throw std::runtime_error("Cannot create MCP directory");
  struct stat st;if(lstat(dir_.c_str(),&st)||!S_ISDIR(st.st_mode)||st.st_uid!=getuid()||(st.st_mode&0077))throw std::runtime_error("MCP directory must be owned by current user with mode 0700");
  lock_=open((dir_+"/emulator.lock").c_str(),O_CREAT|O_RDWR|O_NOFOLLOW,0600);
  if(lock_<0||flock(lock_,LOCK_EX|LOCK_NB))throw std::runtime_error("MCP directory is already in use");
  // A fresh emulator must never execute stale commands from an earlier session.
  DIR* d=opendir(dir_.c_str());if(d){dirent* e;while((e=readdir(d))){std::string n=e->d_name;if(n.size()==36&&(n.substr(32)==".req"||n.substr(32)==".res")&&n.substr(0,32).find_first_not_of("0123456789abcdef")==std::string::npos)unlink((dir_+"/"+n).c_str());}closedir(d);}
  backend_=backend;enabled_=true;paused_=true;contact_=Clock::now();
 }
 // Memory callbacks are from the CPU's speculative debug pass: stop BEFORE the instruction.
 void access(const std::string& kind,uint32_t address,uint8_t value) {
  if(!enabled_||hit_!="null")return;
  for(const auto& bp:breakpoints_)if(bp.kind==kind&&address>=bp.first&&address<=bp.last){
   hit_="{\"kind\":"+quote(kind)+",\"address\":"+std::to_string(address)+",\"value\":"+std::to_string(value)+"}";break;
  }
 }
 void instruction(uint32_t physical_pc) {
  if(!enabled_) return;
  pc_=physical_pc;
  ++ticks_;
  for(const auto& bp:breakpoints_)if(bp.kind=="pc"&&pc_>=bp.first&&pc_<=bp.last){hit_="{\"kind\":\"pc\",\"address\":"+std::to_string(pc_)+"}";break;}
  if(hit_!="null"){paused_=true;reason_="breakpoint";}
  if(remaining_&&!--remaining_){paused_=true;reason_="budget";}
  if(paused_||(ticks_&1023)==0){auto now=Clock::now();if(paused_||now-poll_>std::chrono::milliseconds(10)){poll();poll_=now;}}
  while(paused_){
   if(Clock::now()-contact_>std::chrono::seconds(30)){paused_=false;remaining_=0;reason_="lease_expired";hit_="null";break;}
   usleep(5000);poll();
  }
  hit_="null";
 }
};
#else
class Bridge {
public:
 bool enabled() const { return false; }
 uint16_t buttons(uint16_t raw) { return raw; }
 bool capture_requested() const { return false; }
 std::string capture_path() const { return ""; }
 void captured() {}
 bool auto_capture() const { return false; }
 bool save_requested() const { return false; }
 void saved() {}
 std::string directory() const { return ""; }
 void init(const char* path, Backend) { if(path && *path) throw std::runtime_error("MCP bridge requires a POSIX host"); }
 void access(const std::string&, uint32_t, uint8_t) {}
 void instruction(uint32_t) {}
};
#endif
}
#endif
