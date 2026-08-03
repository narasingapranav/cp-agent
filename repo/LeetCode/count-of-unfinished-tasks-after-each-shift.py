from bisect import bisect_right
class Solution:
    def countTasks(self, tasks: List[int], shifts: List[int]) -> List[int]:
        n=len(tasks)
        prefix=[0]
        for i in tasks:
            prefix.append(prefix[-1]+i)
        total=prefix[-1]
        completed=0
        res=[]
        for s in shifts:
            completed+=s
            if completed>=total:
                res.append(0)
                completed=0
            else:
                m=bisect_right(prefix,completed)-1
                res.append(n-m)
        return res