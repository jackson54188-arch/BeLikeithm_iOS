//
//  SocketDelegate.m
//  Brokenithm-iOS
//
//  Created by ester on 2020/2/29.
//  Copyright © 2020 esterTion. All rights reserved.
//

#import "SocketDelegate.h"

@interface SocketDelegate ()
@end

@implementation SocketDelegate

- (id)init {
    server = [[GCDAsyncSocket alloc] initWithDelegate:(id)self delegateQueue:dispatch_get_main_queue()];
    [self acceptConnection];
    connectedSockets = [[NSMutableArray alloc] initWithCapacity:1];
    [NSNotificationCenter.defaultCenter addObserver:self selector:@selector(becomeInactive) name:UIApplicationWillResignActiveNotification object:nil];
    [NSNotificationCenter.defaultCenter addObserver:self selector:@selector(becomeActive) name:UIApplicationDidBecomeActiveNotification object:nil];
    return [super init];
}
- (void)acceptConnection {
    // This fork and the original Brokenithm both listen on 24864, and only one
    // process can bind it. Stay on a retry loop so the server recovers by
    // itself once the other app is gone, instead of staying disconnected.
    if (![server isDisconnected]) return;
    NSError *error = nil;
    if ([server acceptOnPort:24864 error:&error]) {
        acceptRetryScheduled = NO;
        return;
    }
    if (!acceptRetryScheduled) {
        NSLog(@"error creating server: %@", error);
        acceptRetryScheduled = YES;
    }
    [NSObject cancelPreviousPerformRequestsWithTarget:self selector:@selector(acceptConnection) object:nil];
    [self performSelector:@selector(acceptConnection) withObject:nil afterDelay:1.0];
}

- (void)socket:(GCDAsyncSocket *)sock didAcceptNewSocket:(GCDAsyncSocket *)newSocket {
    @synchronized(connectedSockets)
    {
        [connectedSockets addObject:newSocket];
    }
    NSLog(@"got connection");
    NSString *initResponse = @"\x03WEL";
    NSData *initResp = [initResponse dataUsingEncoding:NSASCIIStringEncoding];
    [newSocket writeData:initResp withTimeout:-1 tag:0];
    [newSocket readDataToLength:1 withTimeout:5 tag:0];
    [self.parentVc connected];
}
- (void)socket:(GCDAsyncSocket *)sock didWriteDataWithTag:(long)tag {}
- (void)socket:(GCDAsyncSocket *)sock didReadData:(NSData *)data withTag:(long)tag {
    switch (tag) {
        case 0: {
            // One-byte length, except 0xFF which introduces a 4-byte length.
            // The input bridge keeps using the short form (LED = 99); video
            // frames need the long form because a JPEG is far above 255 bytes.
            if (data.length < 1) {
                [sock disconnect];
                return;
            }
            uint8_t length = ((const uint8_t*)data.bytes)[0];
            if (length == 0xFF) {
                [sock readDataToLength:4 withTimeout:5 tag:2];
            } else if (length == 0) {
                [sock disconnect];
            } else {
                [sock readDataToLength:length withTimeout:1 tag:1];
            }
            break;
        }
        case 1: {
            // data
            if (data.length < 3) {
                [sock disconnect];
                return;
            }
            NSData *msgData = [data subdataWithRange:NSMakeRange(0, 3)];
            NSString *message = [[NSString alloc] initWithData:msgData encoding:NSASCIIStringEncoding];
            if ([message isEqualToString:@"LED"] && data.length >= 99) {
                NSData *led = [data subdataWithRange:NSMakeRange(3, 96)];
                [self.parentVc updateLed:led];
            }
            
            [sock readDataToLength:1 withTimeout:5 tag:0];
            break;
        }
        case 2: {
            // Extended length, big-endian.
            if (data.length != 4) {
                [sock disconnect];
                return;
            }
            const uint8_t *bytes = (const uint8_t*)data.bytes;
            uint32_t length = ((uint32_t)bytes[0] << 24) | ((uint32_t)bytes[1] << 16)
                            | ((uint32_t)bytes[2] << 8) | (uint32_t)bytes[3];
            if (length < 3 || length > (4u << 20)) {
                [sock disconnect];
                return;
            }
            [sock readDataToLength:length withTimeout:5 tag:3];
            break;
        }
        case 3: {
            // Extended payload: 3-byte type + body.
            if (data.length >= 3) {
                NSString *message = [[NSString alloc] initWithData:
                    [data subdataWithRange:NSMakeRange(0, 3)] encoding:NSASCIIStringEncoding];
                if ([message isEqualToString:@"VID"]) {
                    [self.parentVc updateVideo:
                        [data subdataWithRange:NSMakeRange(3, data.length - 3)]];
                }
            }
            [sock readDataToLength:1 withTimeout:5 tag:0];
            break;
        }
    }
}
- (void)socketDidDisconnect:(GCDAsyncSocket *)sock withError:(NSError *)err {
    if (sock != server)
    {
        NSLog(@"connection ended");
        @synchronized(connectedSockets)
        {
            [connectedSockets removeObject:sock];
            if (connectedSockets.count == 0) {
                [self.parentVc disconnected];
            }
        }
    }
}

- (void)BroadcastData:(NSData*)data {
    for (GCDAsyncSocket* sock in connectedSockets) {
        [sock writeData:data withTimeout:-1 tag:0];
    }
}

- (void)becomeInactive {
    [self.parentVc becomeInactive];
    server.IPv4Enabled = NO;
    server.IPv6Enabled = NO;
    // Iterate a snapshot: removing while enumerating throws once a streamer
    // keeps a second socket open.
    for (GCDAsyncSocket* sock in [connectedSockets copy]) {
        [sock disconnect];
        [connectedSockets removeObject:sock];
    }
    [server disconnect];
}
- (void)becomeActive {
    [self.parentVc becomeActive];
    server.IPv4Enabled = YES;
    server.IPv6Enabled = YES;
    [self acceptConnection];
}

@end

