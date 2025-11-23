#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <sys/epoll.h>
#include <sys/socket.h>
#include <netinet/tcp.h>
#include <netinet/in.h>
#include <fcntl.h>

#define PORT 8765
#define MAX_EVENTS 1024


typedef struct {
    int fd;
    int room;
    int peer_fd;
} User;

User* users[100000]; 
int epfd;

void handle(int fd) {
    static char buf[16384];
    int n = recv(fd, buf, sizeof(buf), MSG_DONTWAIT);
    
    if (n <= 0) {
        // Disconnect
        User* u = users[fd];
        if (u) {
            if (u->peer_fd) users[u->peer_fd]->peer_fd = 0;
            free(u);
            users[fd] = NULL;
        }
        close(fd);
        return;
    }
    
    if (buf[0] == 'J') { 
        int room = *(int*)(buf + 1);
        User* u = users[fd];
        if (!u) {
            u = users[fd] = calloc(1, sizeof(User));
            u->fd = fd;
        }
        u->room = room;
        
        // Find peer in same room
        for (int i = 0; i < 100000; i++) {
            if (users[i] && users[i] != u && users[i]->room == room && !users[i]->peer_fd) {
                u->peer_fd = i;
                users[i]->peer_fd = fd;
                write(fd, "R", 1); 
                write(i, "R", 1);
                break;
            }
        }
        
    } else if (buf[0] == 'S') { 
        User* u = users[fd];
        if (u && u->peer_fd) {
            write(u->peer_fd, buf + 5, n - 5);  
        }
    }
}

int main() {
    int srv = socket(AF_INET, SOCK_STREAM, 0);
    int opt = 1;
    setsockopt(srv, SOL_SOCKET, SO_REUSEADDR, &opt, sizeof(opt));
    setsockopt(srv, SOL_TCP, TCP_NODELAY, &opt, sizeof(opt));
    
    struct sockaddr_in addr = {.sin_family = AF_INET, .sin_port = htons(PORT)};
    bind(srv, (struct sockaddr*)&addr, sizeof(addr));
    listen(srv, 65535);
    fcntl(srv, F_SETFL, O_NONBLOCK);
    
    epfd = epoll_create1(0);
    struct epoll_event ev = {.events = EPOLLIN, .data.fd = srv};
    epoll_ctl(epfd, EPOLL_CTL_ADD, srv, &ev);
    
    struct epoll_event events[MAX_EVENTS];
    
    while (1) {
        int n = epoll_wait(epfd, events, MAX_EVENTS, -1);
        
        for (int i = 0; i < n; i++) {
            if (events[i].data.fd == srv) {
                while (1) {
                    int c = accept(srv, NULL, NULL);
                    if (c < 0) break;
                    
                    fcntl(c, F_SETFL, O_NONBLOCK);
                    int opt = 1;
                    setsockopt(c, SOL_TCP, TCP_NODELAY, &opt, sizeof(opt));
                    
                    ev.events = EPOLLIN | EPOLLET;
                    ev.data.fd = c;
                    epoll_ctl(epfd, EPOLL_CTL_ADD, c, &ev);
                }
            } else {
                handle(events[i].data.fd);
            }
        }
    }
}