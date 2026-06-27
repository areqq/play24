// Uniwersalny SSL-unpinning dla Play24 (OkHttp3 CertificatePinner + TrustManager + Conscrypt)
Java.perform(function () {
    var done = {};
    function once(tag, fn) { if (!done[tag]) { done[tag] = true; try { fn(); console.log("[unpin] " + tag); } catch (e) {} } }

    // 1) OkHttp3 CertificatePinner — wyłącz WSZYSTKIE przeciążenia check/check$okhttp (klasa może być przeniesiona)
    ["okhttp3.CertificatePinner"].forEach(function (cn) {
        try {
            var CP = Java.use(cn);
            ["check", "check$okhttp"].forEach(function (m) {
                if (CP[m]) CP[m].overloads.forEach(function (ov) {
                    ov.implementation = function () { return; };
                });
            });
            once("okhttp3.CertificatePinner(all overloads)", function(){});
        } catch (e) { console.log("[unpin] okhttp err: " + e); }
    });
    // 1a) ZOBFUSKOWANY OkHttp CertificatePinner = okhttp3.b (a()=check, b()=check$okhttp)
    //     Klasa ładuje się dopiero przy 1. żądaniu — ponawiamy aż się pojawi.
    var okhttpTries = 0;
    var okhttpTimer = setInterval(function () {
        okhttpTries++;
        try {
            var OB = Java.use("okhttp3.b");
            OB.a.overloads.forEach(function (ov) { ov.implementation = function () { return; }; });
            OB.b.overloads.forEach(function (ov) { ov.implementation = function () { return; }; });
            clearInterval(okhttpTimer);
            once("okhttp3.b (obfuscated CertificatePinner)", function(){});
        } catch (e) {
            if (okhttpTries > 60) { clearInterval(okhttpTimer); console.log("[unpin] okhttp3.b nieznaleziony po 30s"); }
        }
    }, 500);

    // 1b) skan załadowanych klas po 'CertificatePinner' (gdyby okhttp3 było przemianowane)
    try {
        Java.enumerateLoadedClassesSync().forEach(function (name) {
            if (name.indexOf("CertificatePinner") !== -1 && name !== "okhttp3.CertificatePinner") {
                try {
                    var K = Java.use(name);
                    if (K.check) K.check.overloads.forEach(function (ov) { ov.implementation = function () { return; }; });
                    console.log("[unpin] patched " + name);
                } catch (e) {}
            }
        });
    } catch (e) {}

    // 2) TrustManagerImpl (Conscrypt) verifyChain -> zwróć łańcuch bez weryfikacji
    try {
        var TMI = Java.use("com.android.org.conscrypt.TrustManagerImpl");
        TMI.checkTrustedRecursive.implementation = function (certs, host, clientAuth, untrustedChain, trustAnchorChain, used) {
            return Java.use("java.util.ArrayList").$new();
        };
        TMI.verifyChain.implementation = function (untrustedChain, trustAnchorChain, host, clientAuth, ocspData, tlsSctData) {
            return untrustedChain;
        };
        once("conscrypt.TrustManagerImpl", function(){});
    } catch (e) {}

    // 3) Platform.checkServerTrusted (Conscrypt) -> no-op
    try {
        var Pl = Java.use("com.android.org.conscrypt.Platform");
        Pl.checkServerTrusted.overload(
            'javax.net.ssl.X509TrustManager','[Ljava.security.cert.X509Certificate;','java.lang.String','com.android.org.conscrypt.AbstractConscryptSocket'
        ).implementation = function () { return; };
        once("conscrypt.Platform.checkServerTrusted", function(){});
    } catch (e) {}

    // 4) Własny X509TrustManager (na wszelki wypadek) — przepuść wszystko
    try {
        var X509TM = Java.use('javax.net.ssl.X509TrustManager');
        var SSLContext = Java.use('javax.net.ssl.SSLContext');
        var TM = Java.registerClass({
            name: 'org.unpin.AllowAllTM',
            implements: [X509TM],
            methods: {
                checkClientTrusted: function () {},
                checkServerTrusted: function () {},
                getAcceptedIssuers: function () { return []; }
            }
        });
        var init = SSLContext.init.overload('[Ljavax.net.ssl.KeyManager;','[Ljavax.net.ssl.TrustManager;','java.security.SecureRandom');
        init.implementation = function (km, tm, sr) { init.call(this, km, [TM.$new()], sr); };
        once("X509TrustManager.SSLContext.init", function(){});
    } catch (e) {}

    console.log("[unpin] hooks installed");
});
