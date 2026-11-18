package demo;
import org.springframework.stereotype.Controller;
import org.springframework.web.bind.annotation.*;

@Controller
@RequestMapping({"/settings", "/prefs"})
public class SettingsController {
    static final String VIEW = "settings/llms";

    @GetMapping("/llms")
    public String page() {
        return VIEW;
    }

    @PostMapping("/llms/save")
    @ResponseBody
    public java.util.Map<String, String> save(@RequestParam("enabled") boolean enabled) {
        java.util.Map<String, String> body = new java.util.HashMap<>();
        body.put("status", "success");
        return body;
    }
}
