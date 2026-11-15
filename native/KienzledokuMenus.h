#import <Cocoa/Cocoa.h>

// WebKit's editing shortcuts are routed through the native responder chain.
// Without these menu items Cmd-V/C/X/A do not reach the focused HTML input.
static void KienzledokuInstallMenus(NSWindow *window, NSString *appName) {
    NSMenu *main = [[NSMenu alloc] initWithTitle:@""];
    NSMenuItem *appItem = [[NSMenuItem alloc] initWithTitle:appName action:nil keyEquivalent:@""];
    NSMenu *appMenu = [[NSMenu alloc] initWithTitle:appName];
    NSMenuItem *quit = [appMenu addItemWithTitle:[appName stringByAppendingString:@" schließen"]
                                         action:@selector(performClose:) keyEquivalent:@"q"];
    quit.target = window; // Retains the installer's windowShouldClose check.
    appItem.submenu = appMenu;
    [main addItem:appItem];

    NSMenuItem *editItem = [[NSMenuItem alloc] initWithTitle:@"Bearbeiten" action:nil keyEquivalent:@""];
    NSMenu *edit = [[NSMenu alloc] initWithTitle:@"Bearbeiten"];
    [edit addItemWithTitle:@"Rückgängig" action:NSSelectorFromString(@"undo:") keyEquivalent:@"z"];
    NSMenuItem *redo = [edit addItemWithTitle:@"Wiederholen" action:NSSelectorFromString(@"redo:") keyEquivalent:@"z"];
    redo.keyEquivalentModifierMask = NSEventModifierFlagCommand | NSEventModifierFlagShift;
    [edit addItem:NSMenuItem.separatorItem];
    [edit addItemWithTitle:@"Ausschneiden" action:@selector(cut:) keyEquivalent:@"x"];
    [edit addItemWithTitle:@"Kopieren" action:@selector(copy:) keyEquivalent:@"c"];
    [edit addItemWithTitle:@"Einfügen" action:@selector(paste:) keyEquivalent:@"v"];
    [edit addItemWithTitle:@"Alles auswählen" action:@selector(selectAll:) keyEquivalent:@"a"];
    editItem.submenu = edit;
    [main addItem:editItem];
    NSApp.mainMenu = main;
}
