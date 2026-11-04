#import <Foundation/Foundation.h>
#import <dlfcn.h>
@interface MiBandMediaRemote:NSObject
-(NSString*)state;
@end
@implementation MiBandMediaRemote
-(NSString*)state {
 void *h=dlopen("/System/Library/PrivateFrameworks/MediaRemote.framework/MediaRemote",RTLD_NOW);
 void (*info)(dispatch_queue_t,void(^)(CFDictionaryRef))=dlsym(h,"MRMediaRemoteGetNowPlayingInfo");
 __block NSString *result=nil;
 info(dispatch_get_main_queue(),^(CFDictionaryRef d){result=[(__bridge NSDictionary*)d description]?:@"nil";});
 NSDate *limit=[NSDate dateWithTimeIntervalSinceNow:3];
 while(!result && [limit timeIntervalSinceNow]>0) [[NSRunLoop currentRunLoop] runUntilDate:[NSDate dateWithTimeIntervalSinceNow:.01]];
 return result?:@"timeout";
}
@end
void miband_media(void){ @autoreleasepool { printf("%s\n",[[[MiBandMediaRemote alloc] init] state].UTF8String); exit(0); } }
