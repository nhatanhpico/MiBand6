// Loaded by macOS's Perl so MediaRemote can identify an Apple host on macOS 15.4+.
#import <Foundation/Foundation.h>
#import <dlfcn.h>

static void fail(NSString *message) {
    fprintf(stderr, "%s\n", message.UTF8String);
    exit(1);
}

void miband_media(void) {
    @autoreleasepool {
        void *framework = dlopen("/System/Library/PrivateFrameworks/MediaRemote.framework/MediaRemote", RTLD_NOW);
        void (*getInfo)(dispatch_queue_t, void (^)(CFDictionaryRef)) = dlsym(framework, "MRMediaRemoteGetNowPlayingInfo");
        void (*getPlaying)(dispatch_queue_t, void (^)(Boolean)) = dlsym(framework, "MRMediaRemoteGetNowPlayingApplicationIsPlaying");
        Boolean (*sendCommand)(int, CFDictionaryRef) = dlsym(framework, "MRMediaRemoteSendCommand");
        if (!framework || !getInfo || !getPlaying || !sendCommand) fail(@"macOS media controls are unavailable.");
        NSString *action = [NSString stringWithUTF8String:getenv("MIBAND6_MEDIA_ACTION") ?: "refresh"];
        NSDictionary *commands = @{@"play": @0, @"pause": @1, @"next": @4, @"previous": @5};
        NSNumber *command = commands[action];
        if (command) {
            if (!sendCommand(command.intValue, NULL)) fail(@"macOS could not deliver the playback command.");
            [[NSRunLoop currentRunLoop] runUntilDate:[NSDate dateWithTimeIntervalSinceNow:0.2]];
        }
        __block NSDictionary *metadata = nil;
        __block BOOL infoDone = NO, playingDone = NO, playing = NO;
        getInfo(dispatch_get_main_queue(), ^(CFDictionaryRef value) {
            metadata = [(__bridge NSDictionary *)value copy];
            infoDone = YES;
        });
        getPlaying(dispatch_get_main_queue(), ^(Boolean value) {
            playing = value;
            playingDone = YES;
        });
        NSDate *deadline = [NSDate dateWithTimeIntervalSinceNow:3];
        while ((!infoDone || !playingDone) && deadline.timeIntervalSinceNow > 0)
            [[NSRunLoop currentRunLoop] runUntilDate:[NSDate dateWithTimeIntervalSinceNow:0.01]];
        if (!infoDone || !playingDone) fail(@"macOS did not return the current playback state.");
        NSDictionary *state = @{@"playing": @(playing),
            @"title": metadata[@"kMRMediaRemoteNowPlayingInfoTitle"] ?: @"Mac",
            @"artist": metadata[@"kMRMediaRemoteNowPlayingInfoArtist"] ?: @""};
        NSData *json = [NSJSONSerialization dataWithJSONObject:state options:0 error:nil];
        fwrite(json.bytes, 1, json.length, stdout);
        exit(0);
    }
}
