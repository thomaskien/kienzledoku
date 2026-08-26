#include <gtk/gtk.h>
#include <webkit/webkit.h>

#include <stdio.h>
#include <string.h>

typedef struct {
    const char *start_uri;
    int start_port;
} KienzledokuWindowData;

static gboolean
uri_is_local_session(const char *uri, const KienzledokuWindowData *data)
{
    GError *error = NULL;
    GUri *parsed = g_uri_parse(uri, G_URI_FLAGS_NONE, &error);
    if (parsed == NULL) {
        g_clear_error(&error);
        return FALSE;
    }

    const char *scheme = g_uri_get_scheme(parsed);
    const char *host = g_uri_get_host(parsed);
    int port = g_uri_get_port(parsed);
    gboolean allowed =
        scheme != NULL && g_ascii_strcasecmp(scheme, "http") == 0 &&
        host != NULL && strcmp(host, "127.0.0.1") == 0 &&
        port == data->start_port;

    g_uri_unref(parsed);
    return allowed;
}

static gboolean
uri_is_product_website(const char *uri)
{
    GError *error = NULL;
    GUri *parsed = g_uri_parse(uri, G_URI_FLAGS_NONE, &error);
    if (parsed == NULL) {
        g_clear_error(&error);
        return FALSE;
    }

    const char *scheme = g_uri_get_scheme(parsed);
    const char *host = g_uri_get_host(parsed);
    gboolean allowed =
        scheme != NULL && g_ascii_strcasecmp(scheme, "https") == 0 &&
        host != NULL &&
        (g_ascii_strcasecmp(host, "kienzledoku.de") == 0 ||
         g_ascii_strcasecmp(host, "www.kienzledoku.de") == 0);

    g_uri_unref(parsed);
    return allowed;
}

static gboolean
decide_policy(WebKitWebView *web_view,
              WebKitPolicyDecision *decision,
              WebKitPolicyDecisionType type,
              gpointer user_data)
{
    (void)web_view;
    KienzledokuWindowData *data = user_data;

    if (type != WEBKIT_POLICY_DECISION_TYPE_NAVIGATION_ACTION &&
        type != WEBKIT_POLICY_DECISION_TYPE_NEW_WINDOW_ACTION) {
        return FALSE;
    }

    WebKitNavigationPolicyDecision *navigation =
        WEBKIT_NAVIGATION_POLICY_DECISION(decision);
    WebKitNavigationAction *action =
        webkit_navigation_policy_decision_get_navigation_action(navigation);
    WebKitURIRequest *request = webkit_navigation_action_get_request(action);
    const char *uri = webkit_uri_request_get_uri(request);

    if (uri != NULL &&
        (uri_is_local_session(uri, data) || g_str_has_prefix(uri, "about:"))) {
        webkit_policy_decision_use(decision);
        return TRUE;
    }

    if (uri != NULL && uri_is_product_website(uri)) {
        GError *error = NULL;
        if (!g_app_info_launch_default_for_uri(uri, NULL, &error)) {
            g_warning("Produktwebsite konnte nicht geöffnet werden: %s",
                      error != NULL ? error->message : "unbekannter Fehler");
        }
        g_clear_error(&error);
    }

    webkit_policy_decision_ignore(decision);
    return TRUE;
}

static void
web_view_close(WebKitWebView *web_view, gpointer user_data)
{
    (void)web_view;
    gtk_window_close(GTK_WINDOW(user_data));
}

static void
activate(GtkApplication *application, gpointer user_data)
{
    KienzledokuWindowData *data = user_data;
    GtkWidget *window = gtk_application_window_new(application);
    gtk_window_set_title(GTK_WINDOW(window), "Kienzledoku 1.3.0");
    gtk_window_set_default_size(GTK_WINDOW(window), 1280, 850);
    gtk_window_set_icon_name(GTK_WINDOW(window), "audio-input-microphone");
    gtk_widget_set_size_request(window, 800, 600);

    WebKitNetworkSession *network_session =
        webkit_network_session_new_ephemeral();
    GtkWidget *web_view = g_object_new(
        WEBKIT_TYPE_WEB_VIEW,
        "network-session", network_session,
        NULL);
    g_object_unref(network_session);

    WebKitSettings *settings =
        webkit_web_view_get_settings(WEBKIT_WEB_VIEW(web_view));
    webkit_settings_set_user_agent(
        settings, "Kienzledoku-NativeWindow-Linux/1.3.0");
    webkit_settings_set_enable_developer_extras(settings, FALSE);

    g_signal_connect(
        web_view, "decide-policy", G_CALLBACK(decide_policy), data);
    g_signal_connect(
        web_view, "close", G_CALLBACK(web_view_close), window);

    gtk_window_set_child(GTK_WINDOW(window), web_view);
    webkit_web_view_load_uri(WEBKIT_WEB_VIEW(web_view), data->start_uri);
    gtk_window_present(GTK_WINDOW(window));
}

int
main(int argc, char **argv)
{
    if (argc != 2) {
        fprintf(stderr,
                "usage: kienzledoku_window_linux http://127.0.0.1:PORT/\n");
        return 2;
    }

    GError *error = NULL;
    GUri *parsed = g_uri_parse(argv[1], G_URI_FLAGS_NONE, &error);
    if (parsed == NULL) {
        fprintf(stderr, "Ungültige lokale Kienzledoku-URL: %s\n",
                error != NULL ? error->message : "unbekannter Fehler");
        g_clear_error(&error);
        return 2;
    }

    const char *scheme = g_uri_get_scheme(parsed);
    const char *host = g_uri_get_host(parsed);
    int port = g_uri_get_port(parsed);
    gboolean valid =
        scheme != NULL && g_ascii_strcasecmp(scheme, "http") == 0 &&
        host != NULL && strcmp(host, "127.0.0.1") == 0 &&
        port > 0;
    g_uri_unref(parsed);
    if (!valid) {
        fprintf(stderr,
                "Das Kienzledoku-Fenster akzeptiert nur Loopback-HTTP-URLs.\n");
        return 2;
    }

    KienzledokuWindowData data = {
        .start_uri = argv[1],
        .start_port = port,
    };
    GtkApplication *application = gtk_application_new(
        "de.kienzledoku.app",
        G_APPLICATION_NON_UNIQUE);
    g_signal_connect(application, "activate", G_CALLBACK(activate), &data);
    int status = g_application_run(G_APPLICATION(application), 1, argv);
    g_object_unref(application);
    return status;
}
