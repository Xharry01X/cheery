#include <sys/socket.h>
#include <netinet/in.h>
#include <unistd.h>
#include <sys/epoll.h>
#include <fcntl.h>
#include <string.h>
#include <time.h>
#include <stdio.h>

#define MAX_USERS 200000

int room[MAX_USERS];
time_t timeout[MAX_USERS];
int ep, s;
struct epoll_event e[1024];

int main() {
    s = socket(AF_INET, SOCK_STREAM, 0);
    int r = 1;
    setsockopt(s, SOL_SOCKET, SO_REUSEADDR, &r, sizeof(r));
    
    struct sockaddr_in a;
    memset(&a, 0, sizeof(a));
    a.sin_family = AF_INET;
    a.sin_port = htons(8765);
    bind(s, (struct sockaddr*)&a, sizeof(a));
    listen(s, 1024);
    
    ep = epoll_create1(0);
    struct epoll_event ev;
    ev.events = EPOLLIN;
    ev.data.fd = s;
    epoll_ctl(ep, EPOLL_CTL_ADD, s, &ev);
    
    unsigned char b[512];
    time_t last_check = 0;
    
    while(1) {
        int n = epoll_wait(ep, e, 1024, 1000);
        time_t now = time(NULL);
        
        // Check timeouts every second
        if(now != last_check) {
            for(int i = 3; i < MAX_USERS; i++) {
                if(timeout[i] && now - timeout[i] >= 60) {
                    room[i] = 0;
                    timeout[i] = 0;
                }
            }
            last_check = now;
        }
        
        for(int i = 0; i < n; i++) {
            int fd = e[i].data.fd;
            
            if(fd == s) {
                int c = accept(s, 0, 0);
                if(c > 0 && c < MAX_USERS) {
                    ev.data.fd = c;
                    epoll_ctl(ep, EPOLL_CTL_ADD, c, &ev);
                    printf("[%ld] User connected fd=%d\n", time(NULL), c);
                    fflush(stdout);
                }
            } else {
                int len = recv(fd, b, 512, 0);
                
                if(len <= 0) {
                    close(fd);
                    epoll_ctl(ep, EPOLL_CTL_DEL, fd, 0);
                    
                    if(room[fd] > 1000) {
                        timeout[room[fd]] = now;
                    }
                    room[fd] = 0;
                    timeout[fd] = 0;
                } else {
                    timeout[fd] = 0;
                    
                    unsigned char cmd = b[0];
                    
                    if(cmd == 0x01 && len >= 5) {
                        // 0x01: CREATE room
                        // [cmd:1][code:4]
                        int code = *(int*)(b+1);
                        room[fd] = code;
                    } 
                    else if(cmd == 0x02 && len >= 5) {
                        // 0x02: JOIN room
                        // [cmd:1][code:4]
                        int code = *(int*)(b+1);
                        int found = 0;
                        
                        for(int j = 3; j < MAX_USERS; j++) {
                            if(room[j] == code && room[j] > 1000 && j != fd) {
                                room[fd] = j;
                                room[j] = fd;
                                unsigned char resp = 0x04;  // MATCHED
                                send(fd, &resp, 1, 0);
                                send(j, &resp, 1, 0);
                                found = 1;
                                break;
                            }
                        }
                        
                        if(!found) {
                            room[fd] = code;
                            unsigned char resp = 0x05;  // WAITING
                            send(fd, &resp, 1, 0);
                        }
                    }
                    else if(cmd == 0x03 && room[fd] > 1000) {
                        // 0x03: RELAY data to paired user
                        // [cmd:1][data...]
                        send(room[fd], b, len, 0);
                    }
                }
            }
        }
    }
}