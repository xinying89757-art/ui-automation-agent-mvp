var FindProxyForURL = function(init, profiles) {
    return function(url, host) {
        "use strict";
        var result = init, scheme = url.substr(0, url.indexOf(":"));
        do {
            if (!profiles[result]) return result;
            result = profiles[result];
            if (typeof result === "function") result = result(url, host, scheme);
        } while (typeof result !== "string" || result.charCodeAt(0) === 43);
        return result;
    };
}("+Tx\u7070\u5ea6\u8c03\u8bd5", {
    "+Tx\u7070\u5ea6\u8c03\u8bd5": function(url, host, scheme) {
        "use strict";
        if (/^monitor\.apisix\.leadong\.com$/.test(host)) return "+AWS-P\u7248";
        if (/^monitor\.kong\.leadong\.com$/.test(host)) return "+AWS-P\u7248";
        if (/(?:^|\.)leadong\.com$/.test(host)) return "+\u7070";
        if (/(?:^|\.)leadongshop\.com$/.test(host)) return "+\u7070";
        if (/(?:^|\.)websofast\.cn$/.test(host)) return "+\u7070";
        if (/(?:^|\.)leadongcdn\.cn$/.test(host)) return "+\u7070";
        if (/(?:^|\.)leadongcdn\.com$/.test(host)) return "+\u7070";
        if (/(?:^|\.)sofastcdn\.cn$/.test(host)) return "+\u7070";
        if (/(?:^|\.)wsfcdn\.com$/.test(host)) return "+\u7070";
        if (/(?:^|\.)ldycdn\.com$/.test(host)) return "+\u7070";
        if (/(?:^|\.)ldyjz\.com$/.test(host)) return "+\u7070";
        if (/(?:^|\.)ldmfyh\.com$/.test(host)) return "+\u7070";
        if (/(?:^|\.)ldwebsite\.com$/.test(host)) return "+\u7070";
        return "+__ruleListOf_Tx\u7070\u5ea6\u8c03\u8bd5";
    },
    "+__ruleListOf_Tx\u7070\u5ea6\u8c03\u8bd5": function() {
        var FindProxyForURL = function(init, profiles) {
            return function(url, host) {
                "use strict";
                var result = init, scheme = url.substr(0, url.indexOf(":"));
                do {
                    if (!profiles[result]) return result;
                    result = profiles[result];
                    if (typeof result === "function") result = result(url, host, scheme);
                } while (typeof result !== "string" || result.charCodeAt(0) === 43);
                return result;
            };
        }("+__tempZeroRuleListPac", {
            "+__tempZeroRuleListPac": "DIRECT"
        });
        return FindProxyForURL;
    }.call(this),
    "+AWS-P\u7248": function(url, host, scheme) {
        "use strict";
        if (/^localhost$/.test(host) || /^127\.0\.0\.1$/.test(host) || /^design\.ldwebsitebuilder\.com$/.test(host) || /\.googleapis\.com$/.test(host) || /^ufott51\.iok\.la$/.test(host) || /^ufott51\.6655\.la$/.test(host) || /\.ampproject\.org$/.test(host) || /\.gstatic\.com$/.test(host) || /^view\.officeapps\.live\.com$/.test(host) || /^static\.bomeitong\.com$/.test(host) || /^console\.websofast\.cn$/.test(host) || /\.qq\.com$/.test(host) || /\.qpic\.cn$/.test(host) || /\.qiniup\.com$/.test(host) || /\.qbox\.me$/.test(host) || /^www\.googletagmanager\.com$/.test(host) || /\.share\.baidu\.com$/.test(host) || /^www\.google-analytics\.com$/.test(host) || /^en\.sevenzero\.ml$/.test(host) || /\.baidu\.com$/.test(host) || /\.360\.cn$/.test(host) || /\.so\.com$/.test(host) || /\.mediav\.com$/.test(host) || /\.youdao\.com$/.test(host) || /\.ydstatic\.com$/.test(host) || /\.126\.net$/.test(host) || /^wxvideo\.leadongcdn\.cn$/.test(host) || /^5ornrwxhlkjnj\.leadongcdn\.cn$/.test(host) || /^pvo\.made-in-china\.com$/.test(host) || /^www\.micstatic\.com$/.test(host) || /^www\.paypalobjects\.com$/.test(host) || /\.bootcdn\.net$/.test(host) || /\.alipay\.com$/.test(host) || /\.alipaydev\.com$/.test(host) || /\.asus\.com$/.test(host) || /\.facebook\.com$/.test(host) || /^js\.hcaptcha\.com$/.test(host) || /\.hcaptcha\.com$/.test(host) || /\.paypal\.com$/.test(host) || /^10\.110\.3\.168$/.test(host) || /\.googletagmanager\.com$/.test(host) || /^www\.googleapis\.com$/.test(host)) return "DIRECT";
        return "PROXY 52.83.173.246:7128";
    },
    "+\u7070": function(url, host, scheme) {
        "use strict";
        if (/^127\.0\.0\.1$/.test(host) || /^::1$/.test(host) || /^localhost$/.test(host)) return "DIRECT";
        switch (scheme) {
          case "https":
            return "HTTPS 110.42.247.224:443";
          default:
            return "PROXY 110.42.247.224:80";
        }
    }
});
