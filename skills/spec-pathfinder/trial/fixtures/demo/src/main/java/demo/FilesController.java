package demo;
import org.springframework.stereotype.Controller;
import org.springframework.web.bind.annotation.*;

@Controller
@RequestMapping(path = "/files")
public class FilesController {
    // @GetMapping("/fake") 注释不能生成路由。
    @RequestMapping(value = {"/remove", "/delete"}, method = RequestMethod.POST)
    public String remove(@RequestParam("id") long id) {
        String braces = "不要把 } 和 { 当作方法边界";
        return "redirect:/settings/llms";
    }
}
